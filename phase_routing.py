"""The phase chain as the first routing boundary - and the fallback policy, stated once.

The daemon consults the chain before it answers, but a plan is not a permission slip. This module turns
a plan into one of three actions:

    chain      the plan is consistent with what this session may do; the host proceeds to its normal
               handling (the plan's closure says *what* was matched, never that it may run)
    fallback   nothing in the chain matched, or a read-only capability is unavailable; the existing
               answer path runs and the reason is recorded
    refuse     an execution-class capability is required and not granted. There is no fallback here on
               purpose: falling back would run the same operation through an unrestricted path, which is
               exactly what a `requires_grant` declaration exists to prevent.

A directive that reads (`QUERY`, `MEMQUERY`, `IDENTITY`, `COMPOSE`, `VERIFY`) may fall back. A directive
that changes something (`TOOL`, `GITOP`, `MEMORY`, `CODEX_PLAN`) may not.
"""
from __future__ import annotations

import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
for _candidate in (str(HOST_ROOT / "kuhul-phase-engine-v0.1.0" / "core"),
                   str(HOST_ROOT / "kuhul-phase-engine-v0.1.0"), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import phase_chain  # noqa: E402

READ_VERBS = ("QUERY", "MEMQUERY", "IDENTITY", "COMPOSE", "VERIFY", "EXPLAIN", "LOOKUP")
EXECUTION_VERBS = ("TOOL", "GITOP", "MEMORY", "CODEX_PLAN", "DISPATCH")
# Capabilities that mean "this changes something". Anything not listed is treated as read-class.
GRANTED_CAPABILITIES = {"graph.relations.read"}
GRANTABLE = {"memory.write": "memory writes (/allow memory)",
             "repo.write": "repository writes (/allow git)",
             "file.write": "file writes (/allow)"}


def capability_class(capability: str) -> str:
    name = str(capability or "").lower()
    if name in GRANTABLE or any(word in name for word in ("write", "commit", "persist", "execute")):
        return "execution"
    return "read"


def _observe(event: str, phase: str, request_id: str | None, **detail) -> None:
    """Emit a phase observation only when a request id was supplied: nothing is fabricated."""
    if not request_id:
        return
    try:
        import phase_events
        phase_events.emit(request_id, event, phase=phase, source="host",
                          detail=detail or None)
    except Exception:
        return


def directive_verb(directive: str) -> str:
    return str(directive or "").strip().split(" ", 1)[0].upper()


def route(text: str, *, granted: set | None = None, context: dict | None = None,
          folder: Path | None = None, request_id: str | None = None) -> dict:
    """Resolve the chain and decide: chain, fallback or refuse - with the reason attached.

    When a `request_id` is supplied the host records what it actually did: enter Pop, resolve, exit Pop.
    Without one nothing is emitted, because an observation nobody asked for is an invention.
    """
    granted = set(GRANTED_CAPABILITIES if granted is None else granted)
    _observe("phase_enter", "Pop", request_id, boundary="phase_chain")
    ok = True
    try:
        kwargs = dict(context=context or {})
        if folder is not None:
            kwargs["folder"] = folder
        plan = phase_chain.resolve(text, **kwargs)
        closure = plan.get("closure") or {}
        required = list(closure.get("capabilities") or [])
        missing = [capability for capability in required if capability not in granted]
        verdict = dict(schema="kuhul.routing/1", input=str(text or ""), plan=plan,
                       closure=closure.get("kind"), directive=closure.get("directive"),
                       required=required, missing=missing, granted=sorted(granted),
                       authority="declaration_only", execution=False, mutation=False)

        if closure.get("kind") == "none":
            return dict(verdict, action="fallback",
                        reason="no chain binding matched; the answer path handles it")

        verb = directive_verb(closure.get("directive"))
        execution_class = verb in EXECUTION_VERBS or any(capability_class(c) == "execution"
                                                         for c in required)
        if not missing:
            return dict(verdict, action="chain",
                        reason=("the plan is consistent with this session's grants; the host proceeds"
                                if not execution_class else
                                "the required grant is present for this exact scope; the host proceeds"))
        if execution_class:
            return dict(verdict, action="refuse",
                        reason=(f"{verb or 'execution'} requires {', '.join(missing)}; no fallback runs an "
                                "operation that a requires_grant declaration exists to block"))
        return dict(verdict, action="fallback",
                    reason=f"read-only capability unavailable ({', '.join(missing)}); the answer path runs")
    except BaseException as error:
        ok = False
        _observe("phase_exit", "Pop", request_id, boundary="phase_chain", ok=False,
                 outcome=("cancelled" if isinstance(error, (KeyboardInterrupt, GeneratorExit))
                          else "failed"),
                 error=type(error).__name__)
        raise
    finally:
        if ok:
            _observe("phase_exit", "Pop", request_id, boundary="phase_chain", ok=True, outcome="ok")


def summary(verdict: dict) -> str:
    lines = [f"route · {verdict['input']!r} -> {verdict['action']}",
             f"  closure: {verdict['closure']} · directive: {verdict['directive'] or '(none)'}",
             f"  required: {', '.join(verdict['required']) or '(none)'} · "
             f"missing: {', '.join(verdict['missing']) or '(none)'}",
             f"  reason: {verdict['reason']}",
             "  (declaration_only · the plan is not a permission)"]
    return "\n".join(lines)
