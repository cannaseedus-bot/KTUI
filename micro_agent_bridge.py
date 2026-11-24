"""The Micro Agent bridge: AIML/SRAI may request a declared route; only the host dispatches one.

Four decisions taken before writing this, and enforced in code rather than in prose:

    model URI            model://<registered-alias> is a host-recognised route, and only when declared
    invocation authority the host's capability context decides; AIML text never does
    persona authority    persona cannot add or widen a grant - it is not even read for grants
    AGENT.md             deferred until this bridge works and something consumes it

The rule the review asked to protect: **a rendered answer containing `model://planner` stays text.** Dispatch only
happens for a route *name* that appears in the declaration table below. There is no code path from arbitrary model
output to an invocation.

Every result carries `admitted: false`: the dispatch was authorised by the host's own context, and the result still
grants nothing downstream.
"""
from __future__ import annotations

import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import model_lifecycle  # noqa: E402

SCHEMA = "kuhul://micro-agent/bridge/v1"
STATUSES = ("completed", "refused", "failed")
OUTPUT_TYPES = ("candidate_text", "typed_result")

# Declared routes. A route name is the only thing that can be dispatched; a URI is what it points at.
# Adding an entry here is a host decision, reviewed and tested - not something AIML can produce.
DECLARED_ROUTES = {
    "ASK_PLANNER": dict(scheme="model", target="model://planner", alias="planner",
                        capability="model.inference", output_type="candidate_text"),
    "ASK_WORKER": dict(scheme="model", target="model://worker", alias="worker",
                       capability="model.inference", output_type="candidate_text"),
    "QUERY_RELATIONS": dict(scheme="micronaut", target="micronaut://gml/graph-theory/query",
                            capability="graph.relations.read", output_type="typed_result"),
}


class BridgeError(ValueError):
    """A route request the bridge will not dispatch."""


def route_from_text(text: str) -> dict:
    """Text is never a route. Kept explicit so the refusal has a name and a guard."""
    return dict(ok=False, refused="text_is_not_a_route",
                detail=(f"{str(text)[:80]!r} is rendered text; dispatch requires a declared route name"),
                dispatched=False)


def resolve(route: str, *, declaration: dict, registry: dict | None = None) -> dict:
    """Resolve one declared route name against the host's declarations and the shipped model registry."""
    name = str(route or "").strip()
    if not name:
        return dict(ok=False, refused="route_missing", dispatched=False)
    entry = declaration.get(name)
    if entry is None:
        # A URI, a rendered answer or a made-up name all land here: not declared, not dispatchable.
        return dict(ok=False, refused="route_not_declared", dispatched=False,
                    detail=f"{name[:80]!r} is not a declared route")
    if not str(entry.get("target", "")).startswith("model://") and not \
            str(entry.get("target", "")).startswith("micronaut://"):
        return dict(ok=False, refused="target_scheme", dispatched=False,
                    detail=f"{entry.get('target')!r} is not a registered scheme")
    if entry["scheme"] == "model":
        record = registry if registry is not None else model_lifecycle.load()
        aliases = set((record.get("by_name") or {}).keys())
        alias = entry.get("alias")
        if alias not in aliases:
            return dict(ok=False, refused="unknown_target", dispatched=False,
                        detail=f"{alias!r} is not a registered model alias")
    return dict(ok=True, refused=None, dispatched=False, route=name, **entry)


def dispatch(route: dict, payload: dict | None, *, grants: set | frozenset, request_id: str | None,
             complete_for=None, invoke_for=None, persona: dict | None = None) -> dict:
    """Run one resolved route, or refuse it with a named reason. Never raises for a refusal."""
    capability = route.get("capability")
    granted = set(grants or ())
    envelope = dict(schema=SCHEMA, source="aiml_srai", request_id=request_id,
                    scheme=route.get("scheme"), target=route.get("target"),
                    output_type=route.get("output_type"),
                    # The dispatch may be authorised; the result still grants nothing downstream.
                    admitted=False, authority="declaration_only")

    # persona is accepted so a caller cannot smuggle grants through it: it is never read for capability.
    if persona is not None and not isinstance(persona, dict):
        return dict(envelope, status="refused", refused="persona_invalid", result=None,
                    detail="a persona is declarative metadata, not a capability source")

    if not route.get("ok"):
        return dict(envelope, status="refused", refused=route.get("refused"), result=None,
                    detail=route.get("detail"))
    if capability and capability not in granted:
        return dict(envelope, status="refused", refused="capability_not_granted", result=None,
                    detail=f"{capability!r} is not in the host capability context")

    try:
        if route["scheme"] == "model":
            if complete_for is None:
                return dict(envelope, status="refused", refused="dispatcher_unavailable", result=None,
                            detail="no model completer was supplied")
            result = complete_for(route.get("alias"), payload)
            if not isinstance(result, str) or not result.strip():
                return dict(envelope, status="failed", refused="empty_candidate", result=None,
                            detail="the backend returned no text")
            return dict(envelope, status="completed", refused=None, result=result.strip())
        if route["scheme"] == "micronaut":
            if invoke_for is None:
                return dict(envelope, status="refused", refused="dispatcher_unavailable", result=None,
                            detail="no handler invoker was supplied")
            result = invoke_for(route.get("target"), payload)
            return dict(envelope, status="completed", refused=None, result=result)
        return dict(envelope, status="refused", refused="target_scheme", result=None,
                    detail=f"{route.get('scheme')!r} is not a dispatchable scheme")
    except Exception as error:                    # a failing backend is a failed route, not a crash
        return dict(envelope, status="failed", refused="dispatch_error", result=None,
                    detail=f"{type(error).__name__}: {error}"[:200])


def run(route: str, payload: dict | None, *, grants, request_id=None, declaration=None,
        registry=None, complete_for=None, invoke_for=None, persona=None) -> dict:
    """Resolve then dispatch. The one entry point a turn uses."""
    resolved = resolve(route, declaration=declaration or DECLARED_ROUTES, registry=registry)
    return dispatch(resolved, payload, grants=grants, request_id=request_id,
                    complete_for=complete_for, invoke_for=invoke_for, persona=persona)


def summary(result: dict) -> str:
    if result.get("status") == "completed":
        return (f"bridge · completed · {result.get('scheme')} {result.get('target')} · "
                f"{result.get('output_type')} · {result.get('request_id')} · admitted {result.get('admitted')}")
    return (f"bridge · {result.get('status')} · {result.get('refused')} · {result.get('detail') or ''}").strip()
