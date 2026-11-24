"""Wo: classify a live turn into a task family, deterministically, and never invent a target.

The classifier reads only what the host already knows - the utterance, the session's grants, and the declared
runtime routes - and returns a typed binding:

    task_family        the runtime family it recognised, or "unsupported"
    target_family      the declared family in kuhul://targets/v1, when one maps
    allowed_targets    only when the mapping is deterministic; never a guess
    route_id           which runtime route would serve it
    binding_source     "explicit_command" | "rule" | "aiml_pattern"
    candidate_families every family that matched, when more than one did
    status             "bound" | "ambiguous" | "unsupported"

An ambiguous turn reports its candidates and binds **nothing**. A classification is an observation: the caller may
act on it, but nothing here changes an answer or grants a capability.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import binding_resolver  # noqa: E402

SCHEMA = "kuhul://turn/classification/v1"
# Runtime families this host actually serves, and the declared target family each maps to.
ROUTES = {
    "compose": dict(target_family="full_composition", route_id="compose.paragraph"),
    "memory_query": dict(target_family="uri_binding", route_id="user_memory.answer"),
    "git_operation": dict(target_family="refusal", route_id="gitops"),
    "identity": dict(target_family=None, route_id="identity_text"),
    "conversation": dict(target_family=None, route_id="knowledge"),
    "unsupported": dict(target_family=None, route_id=None),
}
# Each rule is (family, pattern, source). Order matters only for readability: ties are ambiguity, not priority.
RULES = (
    ("compose", re.compile(r"^\s*(?:tell me about|what do you know about|describe)\s+my\b", re.I),
     "rule"),
    ("memory_query", re.compile(r"^\s*what(?:'s| is)\s+my\b.*\?", re.I), "rule"),
    # "what do you know about my dog" is genuinely readable as a memory query *and* as a composition;
    # the classifier reports both rather than picking one.
    ("memory_query", re.compile(r"^\s*what do you know about my\b", re.I), "rule"),
    ("git_operation", re.compile(r"^\s*(?:git|commit|push|pull|branch|status|diff|log)\b", re.I), "rule"),
    ("identity", re.compile(r"^\s*(?:who are you|what is your name|what are you)\b", re.I), "rule"),
)
COMMANDS = {
    "/compose": "compose",
    "/memory": "memory_query",
    "/commit": "git_operation",
    "/push": "git_operation",
    "/sync": "git_operation",
    "/clone": "git_operation",
    "/evidence": "identity",
    "/runtime": "identity",
}


def rule_matches(text: str) -> list[dict]:
    """Every rule whose pattern matches, in declaration order - a tie is ambiguity, not a ranking."""
    found = []
    for family, pattern, source in RULES:
        if pattern.search(str(text or "")):
            found.append(dict(family=family, source=source))
    return found


def classify(text: str, *, registry: dict | None = None, granted: set | None = None) -> dict:
    """Classify one utterance. Returns a typed binding, or a named reason why it cannot."""
    registry = registry or binding_resolver.load()
    granted = set(granted or ())
    utterance = str(text or "").strip()
    base = dict(schema=SCHEMA, utterance=utterance, granted=sorted(granted))

    if not utterance:
        return dict(base, status="unsupported", task_family="unsupported", target_family=None,
                    allowed_targets=[], route_id=None, binding_source=None,
                    candidate_families=[], reason="empty utterance", authority="declaration_only")

    # An explicit command is the strongest deterministic evidence there is.
    command = utterance.split()[0].lower() if utterance.split() else ""
    if command in COMMANDS:
        family = COMMANDS[command]
        return _bind(base, family, source="explicit_command", command=command, registry=registry)
    if command.startswith("/"):
        return dict(base, status="unsupported", task_family="unsupported", target_family=None,
                    allowed_targets=[], route_id=None, binding_source="explicit_command",
                    candidate_families=[], reason=f"{command} is not a classified command",
                    authority="declaration_only")

    matches = rule_matches(utterance)
    if len(matches) > 1:
        # Two families read the same sentence: report both and bind nothing.
        return dict(base, status="ambiguous", task_family=None, target_family=None,
                    allowed_targets=[], route_id=None,
                    binding_source="+".join(sorted({match["source"] for match in matches})),
                    candidate_families=sorted({match["family"] for match in matches}),
                    reason=("more than one rule matched; a classifier must not choose between them"),
                    authority="declaration_only")
    if not matches:
        # Nothing classified it: conversation is the honest default only when no rule spoke at all.
        return _bind(base, "conversation", source="rule", registry=registry)
    return _bind(base, matches[0]["family"], source=matches[0]["source"], registry=registry)


def _bind(base: dict, family: str, *, source: str, registry: dict, command: str | None = None) -> dict:
    route = ROUTES.get(family) or ROUTES["unsupported"]
    target_family = route["target_family"]
    if not target_family:
        return dict(base, status="bound", task_family=family, target_family=None, allowed_targets=[],
                    route_id=route["route_id"], binding_source=source, command=command,
                    candidate_families=[family], reason="this family binds no target",
                    authority="declaration_only")
    binding = binding_resolver.binding(registry, target_family)
    # A deterministic mapping may publish its single target; a constrained one must not choose for the model.
    allowed = list(binding["allowed"]) if binding["mode"] == "deterministic" else []
    return dict(base, status="bound", task_family=family, target_family=target_family,
                allowed_targets=allowed, target_mode=binding["mode"],
                route_id=route["route_id"], binding_source=source, command=command,
                candidate_families=[family],
                reason=(None if allowed else
                        f"{target_family} allows {len(binding['allowed'])} target(s); Wo does not pick one"),
                authority="declaration_only")


def observe(binding: dict, request_id: str | None, *, phase: str = "Wo") -> None:
    """Record the classification as Wo work: enter, classify, exit. Silent without a request id."""
    if not request_id:
        return
    try:
        import phase_events
        phase_events.emit(request_id, "phase_enter", phase=phase, source="host",
                          detail={"operation": "turn_classifier.classify"})
        phase_events.emit(request_id, "phase_exit", phase=phase, source="host",
                          detail={"operation": "turn_classifier.classify",
                                  "ok": binding.get("status") == "bound",
                                  "outcome": ("ok" if binding.get("status") == "bound" else "failed"),
                                  "family": binding.get("task_family"),
                                  "status": binding.get("status"),
                                  "source": binding.get("binding_source"),
                                  "candidates": binding.get("candidate_families") or [],
                                  "targets": binding.get("allowed_targets") or []})
    except Exception:
        return


def summary(binding: dict) -> str:
    status = binding.get("status")
    family = binding.get("task_family") or "(none)"
    candidates = binding.get("candidate_families") or []
    detail = f"Wo · {status} · {family} · via {binding.get('binding_source') or '-'}"
    if candidates and status == "ambiguous":
        detail += f" · candidates {', '.join(candidates)}"
    if binding.get("allowed_targets"):
        detail += f" · targets {', '.join(binding['allowed_targets'])}"
    if binding.get("route_id"):
        detail += f" · route {binding['route_id']}"
    return detail
