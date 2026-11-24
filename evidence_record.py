"""Inference evidence records: what happened on a turn, and what the corpus saved.

The review's question is quantitative - *how much reasoning work does the AIML corpus eliminate, and when
does the smaller model perform as well as the advisor?* - so this module records the facts a measurement
needs, and refuses to invent the ones it cannot observe.

A record (`kuhul-inference-record/1`) carries the phase-chain outcome, the micronaut and its binding, the
reported model identity, the retrieval evidence count, the proposed operators, schema validation, XCFE
admission, token usage and latency. Two rules:

    tokens and latency are measurements    when the host did not observe them, they are None - not 0
    admission is not observed here         a record says `admitted: false` because nothing admits

`compare()` runs a task list through three paths - corpus only, corpus + worker, corpus + advisor - and
reports the work each performed: how many turns the corpus handled without a model, how many needed one,
which backend was selected, and the measured latency. Answer *quality* is `None` here on purpose: judging
it needs real inference and a held-out grader, and this module will not pretend to have run them.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import ledger_plugin  # noqa: E402
import model_router  # noqa: E402
import phase_routing  # noqa: E402

SCHEMA = "kuhul-inference-record/1"
LOG = HOST_ROOT / "logs" / "inference" / "records.jsonl"
CLOSURES = ("none", "redirected", "delegated", "refused")
FIELDS = ("recorded_at", "input", "closure", "routing_action", "micronaut", "binding",
          "model_id", "retrieval", "operators", "schema_validation", "admission",
          "tokens", "latency_ms")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def build(*, input_text: str, routing: dict | None = None, binding: dict | None = None,
          model_id: str | None = None, retrieval: dict | None = None,
          operators: list | None = None, schema_validation: str | None = None,
          tokens: dict | None = None, latency_ms: float | None = None,
          micronaut: str | None = None) -> dict:
    """Assemble one record from what the caller actually observed."""
    routing = routing or {}
    closure = routing.get("closure")
    if closure is not None and closure not in CLOSURES:
        raise ValueError(f"closure {closure!r} is not one of {CLOSURES}")
    record = dict(schema=SCHEMA, recorded_at=_now(), input=str(input_text or ""),
                  closure=closure, routing_action=routing.get("action"),
                  micronaut=micronaut or (binding or {}).get("micronaut"),
                  binding=(binding or {}).get("selected"),
                  model_id=model_id if model_id else None,
                  retrieval=dict(retrieval or {}) or None,
                  operators=list(operators or []),
                  schema_validation=schema_validation,
                  admission=dict(admitted=False, authority="declaration_only",
                                 note="a record observes; it never admits"),
                  tokens=dict(tokens) if tokens else None,
                  # Integer milliseconds on purpose: the evidence log is chained through the ledger,
                  # whose canonical form refuses floats so records stay byte-stable.
                  latency_ms=int(round(float(latency_ms))) if latency_ms is not None else None,
                  execution=False, mutation=False)
    return record


def append(record: dict, path: Path = LOG) -> dict:
    """Chain the record into the evidence log, so the log is tamper-evident like the audit ledger."""
    path = Path(path)
    chained = ledger_plugin.append({"kind": "inference-record", "payload": record}, path,
                                   verify_first=True)
    return dict(record, evidence_sequence=chained["sequence"],
                evidence_hash=chained["content_hash"])


def load(path: Path = LOG) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line)["payload"])
        except (json.JSONDecodeError, KeyError):
            continue
    return rows


def verify(path: Path = LOG) -> dict:
    return ledger_plugin.verify(path)


def summarise(records: list[dict]) -> dict:
    """Aggregate what was measured, and say plainly what was not."""
    records = list(records or [])
    latencies = [record["latency_ms"] for record in records
                 if isinstance(record.get("latency_ms"), (int, float))]
    tokens = [record["tokens"]["completion"] for record in records
              if isinstance(record.get("tokens"), dict)
              and isinstance(record["tokens"].get("completion"), int)]
    by_closure: dict[str, int] = {}
    for record in records:
        key = str(record.get("closure") or "unknown")
        by_closure[key] = by_closure.get(key, 0) + 1
    return dict(schema=SCHEMA, records=len(records), by_closure=by_closure,
                model_calls=sum(1 for record in records if record.get("binding")),
                corpus_handled=sum(1 for record in records if not record.get("binding")),
                latency_mean_ms=(int(round(sum(latencies) / len(latencies))) if latencies else None),
                latency_max_ms=(int(round(max(latencies))) if latencies else None),
                tokens_total=(sum(tokens) if tokens else None),
                tokens_measured=bool(tokens),
                note=("counts are observed; means are None where nothing was measured"
                      if not latencies or not tokens else
                      "counts, latency and tokens are all observed"))


PATHS = {
    "aiml_only": dict(invoke=False, preference=None),
    "aiml_worker": dict(invoke=True, preference="fast"),
    "aiml_advisor": dict(invoke=True, preference="deep"),
}


def compare(tasks: list[str], *, router: dict | None = None, granted: set | None = None,
            paths: tuple[str, ...] = ("aiml_only", "aiml_worker", "aiml_advisor"),
            probes: dict | None = None) -> dict:
    """Run the same tasks through each path and report the work each performed.

    This measures routing and eliminated model calls. `answer_quality` is None because no inference is
    performed here: a real comparison needs live completions and a grader, and inventing either would
    make the numbers useless.
    """
    router = router or model_router.load()
    granted = granted if granted is not None else {"graph.relations.read"}
    probes = probes if probes is not None else model_router.healthy(router)
    results = {}
    for name in paths:
        settings = PATHS[name]
        started = time.monotonic()
        rows = []
        for task in tasks:
            routing = phase_routing.route(task, granted=granted)
            entry = dict(input=str(task), closure=routing.get("closure"),
                         action=routing.get("action"), binding=None, model_id=None)
            if settings["invoke"] and routing["action"] == "fallback":
                binding = model_router.select(router, "micronaut://v1/compose",
                                              preference=settings["preference"], probes=probes)
                entry["binding"] = binding.get("selected")
                entry["model_id"] = (probes.get(binding.get("selected")) or {}).get("models") or None
                entry["route_ok"] = bool(binding.get("ok"))
            else:
                entry["route_ok"] = routing["action"] in ("chain", "refuse")
            rows.append(entry)
        # `corpus_handled` is a property of the turn (the chain resolved it or refused it), not of the
        # path: a path that never invokes a model must not look like it handled everything.
        handled = sum(1 for row in rows if row["action"] in ("chain", "refuse"))
        results[name] = dict(
            path=name, tasks=len(tasks),
            corpus_handled=handled,
            model_invocations=sum(1 for row in rows if row["binding"]),
            refused=sum(1 for row in rows if row["action"] == "refuse"),
            route_ok=sum(1 for row in rows if row["route_ok"]),
            answer_quality=None,
            latency_ms=int(round((time.monotonic() - started) * 1000)),
            tokens=None, rows=rows)
    baseline = results.get("aiml_only", {})
    eliminated = int(baseline.get("corpus_handled") or 0)
    return dict(schema="kuhul-inference-comparison/1", tasks=len(tasks), paths=results,
                corpus_eliminated_model_calls=eliminated,
                note=("route_ok counts turns the chosen path could handle; answer_quality and tokens are "
                      "None because this comparison performs no inference"),
                execution=False, authority="declaration_only")
