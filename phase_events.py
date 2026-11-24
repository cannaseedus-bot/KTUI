"""`kuhul://phase-event/v1`: the smallest honest observation stream for a phase trace.

The rule this exists to enforce:

    a model returning {"phase": "Sek"} is NOT evidence that Sek executed

So events are emitted only by the host, only where something actually happens, and the four families are kept
apart because inferring one from another is exactly how a screen starts lying:

    phase_enter / phase_exit   the host entered or exited an instrumented phase
    proposal_generated         a model emitted a proposal
    proposal_validated         a validator checked a proposal and recorded its verdict
    execution_admitted         an authorized gate explicitly admitted execution

An incomplete trace stays incomplete: `observe()` never fills in the phases that "should" have run.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
for _candidate in (str(HOST_ROOT / "kuhul-phase-engine-v0.1.0" / "core"), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import plan_graph  # noqa: E402

SCHEMA = "kuhul://phase-event/v1"
FAMILIES = ("phase_enter", "phase_exit", "proposal_generated", "proposal_validated",
            "execution_admitted")
SOURCES = ("host", "validator", "xcfe")
PHASES = plan_graph.PHASES

_lock = threading.Lock()
_traces: dict[str, list[dict]] = {}
_sequence: dict[str, int] = {}
_clock = time.monotonic


class EventError(ValueError):
    """An event the contract does not permit."""


def emit(request_id: str, event: str, *, phase: str | None = None, source: str = "host",
         detail: dict | None = None) -> dict:
    """Record one observed event. Refuses anything it cannot attribute to a host-side actor."""
    identifier = str(request_id or "").strip()
    if not identifier:
        raise EventError("an event needs a request id")
    if event not in FAMILIES:
        raise EventError(f"{event!r} is not one of {FAMILIES}")
    if source not in SOURCES:
        raise EventError(f"{source!r} is not one of {SOURCES}")
    if phase is not None:
        declared = str(phase).strip()
        phase = plan_graph.PHASE_ALIASES.get(declared.lower())
        if phase is None:
            raise EventError(f"{declared!r} is not a registered phase")
    if event.startswith("phase_") and phase is None:
        raise EventError("a phase event needs a phase")
    if event == "phase_exit" and not _traces.get(identifier):
        raise EventError("a phase cannot exit before it entered")
    record = dict(schema=SCHEMA, request_id=identifier, event=event, phase=phase,
                  source=source, authority="observed", detail=dict(detail or {}),
                  sequence=0, monotonic=round(_clock(), 6))
    with _lock:
        _sequence[identifier] = _sequence.get(identifier, 0) + 1
        record["sequence"] = _sequence[identifier]
        _traces.setdefault(identifier, []).append(record)
    return record


def events(request_id: str) -> list[dict]:
    with _lock:
        return list(_traces.get(str(request_id or ""), []))


def observe(request_id: str) -> dict:
    """What the host actually did for this request - and nothing it did not."""
    trace = events(request_id)
    if not trace:
        return dict(schema=SCHEMA, request_id=str(request_id or ""), observed=False,
                    active_phase=None, last_phase=None, state="no_observations", sequence=0,
                    events=[], complete=False,
                    note="no events were recorded; the trace is unknown, not empty by design")
    entered = [record for record in trace if record["event"] == "phase_enter"]
    exited = [record for record in trace if record["event"] == "phase_exit"]
    active = [record for record in entered
              if record["phase"] not in {done["phase"] for done in exited}]
    failed = [record for record in trace
              if record["event"] == "phase_exit" and not record["detail"].get("ok", True)]
    state = ("failed" if failed else
             "active" if active else
             "exited" if exited else "unknown")
    return dict(schema=SCHEMA, request_id=str(request_id), observed=True, failed=bool(failed),
                active_phase=(active[-1]["phase"] if active else None),
                last_phase=entered[-1]["phase"] if entered else None,
                state=state, sequence=trace[-1]["sequence"], events=trace,
                complete=bool(entered) and len(entered) == len(exited),
                phases=[record["phase"] for record in entered],
                families=sorted({record["event"] for record in trace}),
                note=("an incomplete trace stays incomplete: absent phases were not observed, "
                      "and none are filled in"))


def reset(request_id: str | None = None) -> None:
    """Test helper: forget one trace, or all of them."""
    with _lock:
        if request_id is None:
            _traces.clear()
            _sequence.clear()
        else:
            _traces.pop(str(request_id), None)
            _sequence.pop(str(request_id), None)


def summary(view: dict) -> str:
    if not view.get("observed"):
        return f"phase trace · {view['request_id'] or '(none)'} · {view['state']}"
    phases = " -> ".join(view["phases"]) or "(none)"
    return (f"phase trace · {view['request_id']} · {view['state']} · {phases} · "
            f"{len(view['events'])} event(s) · sequence {view['sequence']}")
