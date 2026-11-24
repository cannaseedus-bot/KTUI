"""Lease-wrapped inference: a cold backend is woken once, used under a lease, and released in a finally.

Three things the review asked for, and one safeguard:

    planning is not invoking        `select()` may name a cold model; nothing is woken until `infer()`
    one startup per cold model      a per-model single-flight lock, so two micronauts cannot launch twice
    the lease covers the whole call `finally` releases it, including errors and timeouts
    cold starts are measured apart  wake / inference / total latencies, `model_was_cold`, `lease_released`

Ownership stays with the lifecycle manager: a restart does not adopt a process that merely listens on a
registered port, and `infer()` only stops nothing - it releases a lease.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import evidence_record  # noqa: E402
import model_lifecycle  # noqa: E402
import model_router  # noqa: E402

SCHEMA = "kuhul-inference-session/1"
MEASUREMENTS = ("wake_latency_ms", "inference_latency_ms", "total_latency_ms",
                "model_was_cold", "lease_released")


class SessionError(ValueError):
    """An inference request that the lifecycle did not permit."""


def _host_call(host, name, *args):
    target = host[name] if isinstance(host, dict) else getattr(host, name)
    return target(*args)


class Waker:
    """Single-flight per model: concurrent callers share one startup and then take their own lease."""

    def __init__(self, lifecycle: model_lifecycle.Lifecycle):
        self.lifecycle = lifecycle
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self.wakes: dict[str, int] = {}

    def _lock_for(self, name: str) -> threading.Lock:
        with self._guard:
            if name not in self._locks:
                self._locks[name] = threading.Lock()
            return self._locks[name]

    def ensure(self, name: str) -> dict:
        """Wake at most once per model, even under concurrent requests."""
        with self._lock_for(name):
            started = time.monotonic()
            before = self.lifecycle.state_of(name)
            outcome = self.lifecycle.ensure(name)
            elapsed = int(round((time.monotonic() - started) * 1000))
            if outcome.get("started") and not outcome.get("timeout"):
                self.wakes[name] = self.wakes.get(name, 0) + 1
            return dict(outcome, model_was_cold=before == "cold", wake_latency_ms=elapsed)


def infer(waker: Waker, model: str, conversation: list[dict], complete, *, record: bool = True,
          request_id: str | None = None) -> dict:
    """Acquire, dispatch, release. The lease is released even when the call raises."""
    started = time.monotonic()
    wake = waker.ensure(model)
    if wake.get("state") != "hot":
        return dict(schema=SCHEMA, model=model, ok=False, refused="model_not_ready",
                    wake=wake, inference_latency_ms=None, total_latency_ms=None,
                    model_was_cold=wake.get("model_was_cold"), lease_released=True,
                    error=wake.get("note") or "the backend did not become ready")
    lease = waker.lifecycle.acquire(model)
    inference_started = time.monotonic()
    error = None
    reply = None
    try:
        reply = complete(conversation)
    except Exception as problem:                      # noqa: BLE001 - reported, never hidden
        error = f"{type(problem).__name__}: {problem}"[:200]
    finally:
        inference_latency = int(round((time.monotonic() - inference_started) * 1000))
        released = False
        try:
            waker.lifecycle.release(model)
            released = True
        except Exception:
            released = False
        total = int(round((time.monotonic() - started) * 1000))
    outcome = dict(schema=SCHEMA, model=model, ok=error is None and reply is not None,
                   reply=reply, error=error, wake=wake,
                   wake_latency_ms=wake.get("wake_latency_ms"),
                   inference_latency_ms=inference_latency, total_latency_ms=total,
                   model_was_cold=bool(wake.get("model_was_cold")),
                   lease_released=released, leases_after=lease.get("leases"),
                   authority="declaration_only", execution=False)
    if record:
        try:
            evidence_record.append(evidence_record.build(
                input_text="", request_id=request_id, inference="model",
                model_id=(reply or {}).get("model") if isinstance(reply, dict) else None,
                latency_ms=total, tokens=(dict(total=reply.get("completion_tokens"))
                                          if isinstance(reply, dict)
                                          and isinstance(reply.get("completion_tokens"), int)
                                          else None),
                schema_validation=("ok" if outcome["ok"] else "error"),
                operators=[]))
        except Exception as problem:                  # a lost observation must not lose the answer
            outcome["record_error"] = f"{type(problem).__name__}: {problem}"[:160]
    return outcome


def router_view(router: dict, lifecycle: model_lifecycle.Lifecycle) -> dict:
    """`registered_and_wakeable` is not `running_and_healthy`: a cold backend is still a candidate."""
    view = {}
    for name in router.get("models") or {}:
        state = lifecycle.state_of(name)
        view[name] = dict(state=state, healthy=state == "hot", wakeable=name in lifecycle.declaration["by_name"])
    return view


def select(router: dict, micronaut: str, *, lifecycle: model_lifecycle.Lifecycle | None = None,
           allow_cold: bool = True, features: tuple[str, ...] = (), preference: str | None = None) -> dict:
    """Selection that can return a cold-but-registered model, with the distinction made explicit."""
    probes = {}
    if lifecycle is not None:
        probes = {name: dict(ok=view["healthy"], models=[name])
                  for name, view in router_view(router, lifecycle).items()}
    binding = model_router.select(router, micronaut, preference=preference, features=features,
                                  probes=probes or None)
    if not binding.get("ok") and allow_cold and lifecycle is not None:
        declared = (router.get("routing") or {}).get(micronaut)
        if declared and declared in (lifecycle.declaration.get("by_name") or {}):
            model = router["models"][declared]
            missing = [feature for feature in features if feature not in model["features"]]
            if not missing:
                return dict(binding, ok=True, selected=declared, base_url=model["base_url"],
                            cold=True, refused=None,
                            note="registered and wakeable, not currently running")
    return dict(binding, cold=False)


def summary(outcome: dict) -> str:
    state = "cold start" if outcome.get("model_was_cold") else "warm"
    return (f"{outcome['model']} · {state} · wake {outcome.get('wake_latency_ms')} ms · "
            f"inference {outcome.get('inference_latency_ms')} ms · total {outcome.get('total_latency_ms')} ms · "
            f"lease released {outcome.get('lease_released')}"
            + (f" · error {outcome['error']}" if outcome.get("error") else ""))
