"""The model router: which inference backend serves which micronaut - and whether one is needed at all.

Two rules from the review, both enforced here:

**Only registered endpoints are probed.** The manifest names them; the router never scans ports, and an
endpoint that merely answers on 9040 is not a model because it responded. An unregistered URL is refused
before any request is made.

**AIML answers first.** `plan_invocation()` asks the phase chain whether the corpus already handles the
turn. If it does, no model is invoked - which is the whole point of a shared corpus: the LLM is the
exception, not the entry point.

Selection is deterministic: the micronaut's declared model first, then the preference order from the
manifest, filtered to endpoints whose `/models` probe succeeded and that declare the required features.
A refusal names what was missing.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import phase_routing  # noqa: E402

MANIFEST = PACKAGE / "data" / "models.json"
SCHEMA = "kuhul-model-router/v1"


class RouterError(ValueError):
    """A router manifest that contradicts its own contract."""


def load(path: Path = MANIFEST) -> dict:
    """Parse and validate the router: models, routing, preferences and the probe policy."""
    path = Path(path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, problems=[dict(code="unreadable", detail=str(error))], models={})
    problems: list[dict] = []
    if record.get("schema") != SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}"))
    if record.get("authority") != "declaration_only":
        problems.append(dict(code="authority", detail="a router manifest is declaration_only"))
    models: dict[str, dict] = {}
    for name, entry in (record.get("models") or {}).items():
        base_url = str(entry.get("base_url") or "")
        if not base_url.startswith(("http://127.0.0.1", "http://localhost", "https://")):
            problems.append(dict(code="base_url",
                                 detail=f"{name}: {base_url!r} is not a loopback or https endpoint"))
        if not base_url.rstrip("/").endswith("/v1"):
            problems.append(dict(code="base_url", detail=f"{name}: expected a /v1 base url"))
        features = [str(feature) for feature in entry.get("features") or []]
        if not features:
            problems.append(dict(code="features", detail=f"{name}: declares no features"))
        models[name] = dict(name=name, base_url=base_url.rstrip("/"), role=entry.get("role"),
                            preference=entry.get("preference"), features=features)
    routing = {str(k): str(v) for k, v in (record.get("routing") or {}).items()}
    for micronaut, target in routing.items():
        if target not in models:
            problems.append(dict(code="routing", detail=f"{micronaut} -> {target!r} is not a model"))
    preferences = {str(k): [str(name) for name in v]
                   for k, v in (record.get("preferences") or {}).items()}
    for name, order in preferences.items():
        unknown = [model for model in order if model not in models]
        if unknown:
            problems.append(dict(code="preference", detail=f"{name}: {unknown}"))
    policy = record.get("policy") or {}
    if not policy.get("require_registered"):
        problems.append(dict(code="policy",
                             detail="require_registered must be true: a responding port is not a model"))
    probe = str(policy.get("probe") or "/models")
    timeout = float(policy.get("timeout_seconds") or 2)
    return dict(ok=not problems, problems=problems, models=models, routing=routing,
                preferences=preferences, probe=probe, timeout=timeout,
                authority=record.get("authority"))


# -- health ------------------------------------------------------------------------------------------
def health(router: dict, name: str, *, probe=None) -> dict:
    """Probe one registered endpoint's `/models`. Nothing unregistered is ever contacted."""
    model = (router.get("models") or {}).get(str(name))
    if model is None:
        return dict(ok=False, model=str(name), refused="model_not_registered",
                    reason=f"{name!r} is not in the router manifest")
    url = model["base_url"] + str(router.get("probe") or "/models")
    started = time.monotonic()
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=float(router.get("timeout") or 2)) as response:
            body = response.read().decode("utf-8", "replace")
            status = response.status
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        return dict(ok=False, model=name, url=url, refused="unreachable",
                    reason=f"{type(error).__name__}: {error}"[:200],
                    latency_ms=round((time.monotonic() - started) * 1000, 1))
    latency = round((time.monotonic() - started) * 1000, 1)
    listed = []
    try:
        document = json.loads(body)
        listed = [str(entry.get("id")) for entry in document.get("data") or []
                  if isinstance(entry, dict) and entry.get("id")]
    except json.JSONDecodeError:
        return dict(ok=False, model=name, url=url, status=status, refused="unreadable_probe",
                    reason="the endpoint answered, but not with a model list",
                    latency_ms=latency)
    return dict(ok=status == 200 and bool(listed), model=name, url=url, status=status,
                models=listed, latency_ms=latency, refused=None if listed else "no_models_listed")


def healthy(router: dict, *, names=None) -> dict[str, dict]:
    """Probe the registered endpoints (or a subset) and keep the results."""
    return {name: health(router, name) for name in (names or (router.get("models") or {}))}


# -- selection ---------------------------------------------------------------------------------------
def select(router: dict, micronaut_uri: str, *, preference: str | None = None,
           features: tuple[str, ...] = (), probes: dict | None = None) -> dict:
    """Choose a backend for one micronaut: declared first, then preference order, healthy only."""
    routed = (router.get("routing") or {}).get(str(micronaut_uri))
    if routed is None and preference is None:
        # An unrouted micronaut gets no backend: a binding the manifest never declared is not a binding.
        return dict(schema="kuhul-model-binding/1", ok=False, micronaut=str(micronaut_uri),
                    selected=None, refused="micronaut_not_routed",
                    declared=sorted(router.get("routing") or {}),
                    authority="declaration_only", execution=False, admitted=False,
                    reason="the manifest declares no model for this micronaut")
    order: list[str] = []
    if routed:
        order.append(routed)
    preferred = preference or ((router["models"].get(routed) or {}).get("preference")
                               if routed else None)
    for name in (router.get("preferences") or {}).get(preferred or "", []):
        if name not in order:
            order.append(name)
    for name in (router.get("models") or {}):
        if name not in order:
            order.append(name)
    probes = probes if probes is not None else healthy(router, names=order)
    rejected: list[dict] = []
    for name in order:
        model = router["models"].get(name)
        probe = probes.get(name) or {}
        if model is None:
            rejected.append(dict(model=name, reason="not_registered"))
            continue
        if not probe.get("ok"):
            rejected.append(dict(model=name, reason=probe.get("refused") or "unhealthy"))
            continue
        missing = [feature for feature in features if feature not in model["features"]]
        if missing:
            rejected.append(dict(model=name, reason="missing_features", detail=missing))
            continue
        return dict(schema="kuhul-model-binding/1", ok=True, micronaut=str(micronaut_uri),
                    selected=name, base_url=model["base_url"], role=model["role"],
                    preference=preferred, order=order, rejected=rejected,
                    authority="declaration_only", execution=False, admitted=False,
                    note="a binding names a backend; invoking it is a separate, admitted operation")
    return dict(schema="kuhul-model-binding/1", ok=False, micronaut=str(micronaut_uri),
                selected=None, refused="no_healthy_endpoint", order=order, rejected=rejected,
                authority="declaration_only", execution=False, admitted=False,
                reason="every registered endpoint for this micronaut failed its probe or its features")


def plan_invocation(router: dict, text: str, *, granted: set | None = None,
                    preference: str | None = None, features: tuple[str, ...] = (),
                    probes: dict | None = None, folder: Path | None = None) -> dict:
    """Ask the corpus first. A model is proposed only when the corpus does not already answer.

    `folder` points the phase chain at a different manifest set, which is what a test needs to exercise
    the refuse case (the shipped manifests declare no execution-class binding).
    """
    routing = phase_routing.route(text, granted=granted, folder=folder)
    verdict = dict(schema="kuhul-invocation/1", input=str(text or ""),
                   routing_action=routing["action"], closure=routing.get("closure"),
                   authority="declaration_only", execution=False)
    if routing["action"] in ("chain", "refuse"):
        return dict(verdict, invoke_model=False,
                    reason=(f"the phase chain handled this turn ({routing['action']}); no tokens spent"
                            if routing["action"] == "chain" else
                            f"the chain refused this turn ({routing['reason']}); a model cannot override it"))
    binding = select(router, "micronaut://v1/compose", preference=preference, features=features,
                     probes=probes)
    return dict(verdict, invoke_model=bool(binding["ok"]), binding=binding,
                reason=("the corpus had no answer; the model is proposed" if binding["ok"]
                        else "the corpus had no answer and no registered endpoint is available"))


def summary(router: dict) -> str:
    if not router["ok"]:
        lines = ["model router · INVALID"]
        lines += [f"  {problem['code']}: {problem['detail']}" for problem in router["problems"]]
        return "\n".join(lines)
    lines = [f"model router · {len(router['models'])} model(s) · {len(router['routing'])} route(s) · "
             f"{router['authority']}"]
    for name, model in sorted(router["models"].items()):
        lines.append(f"  {name:8} {model['role']:18} {model['base_url']:32} {model['features']}")
    for micronaut, target in sorted(router["routing"].items()):
        lines.append(f"  {micronaut:26} -> {target}")
    lines.append("  (declaration_only · a binding is not an invocation)")
    return "\n".join(lines)
