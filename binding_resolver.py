"""Wo binds the permitted target before the model runs, and a conflict is recorded, never overwritten.

The measured failure this addresses: the operator graph and the phase are usually right while the target is
choosing a **registered but not authorized** URI. So the binding moves into Wo, with two modes:

    deterministic   exactly one allowed target - Wo resolves it and the model is not asked
    constrained     several allowed - the model may propose one, and Ch'en checks membership
    unbound         the family permits none (refusals, unknown facts) - nothing to bind

Two rules the review insisted on:

    the live path must not read the evaluation corpus   the authorized set comes from `kuhul://targets/v1`
    a conflict is evidence, not a correction            the model's raw target is kept and the conflict is
                                                        recorded with `admitted: false`
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

REGISTRY = PACKAGE / "data" / "targets.json"
SCHEMA = "kuhul://targets/v1"
MODES = ("deterministic", "constrained", "unbound")


def load(path: Path | None = None) -> dict:
    path = Path(path or REGISTRY)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, problems=[dict(code="unreadable", detail=str(error))], families={})
    problems = []
    if record.get("schema") != SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}"))
    if record.get("authority") != "declaration_only":
        problems.append(dict(code="authority", detail="a target registry is declaration_only"))
    families = {}
    for name, entry in (record.get("families") or {}).items():
        allowed = [str(target) for target in entry.get("allowed") or []]
        mode = entry.get("mode")
        if mode not in MODES:
            problems.append(dict(code="mode", detail=f"{name}: {mode!r}"))
        expected_mode = ("unbound" if not allowed else
                         "deterministic" if len(allowed) == 1 else "constrained")
        if mode in MODES and mode != expected_mode:
            problems.append(dict(code="mode_mismatch",
                                 detail=f"{name}: {mode!r} declared for {len(allowed)} target(s), "
                                        f"expected {expected_mode!r}"))
        families[name] = dict(allowed=allowed, mode=mode)
    return dict(ok=not problems, problems=problems, families=families,
                default=record.get("default") or dict(allowed=[], mode="unbound"))


def binding(registry: dict, family: str) -> dict:
    """What Wo may bind for a task family - derived from the registry, not from any expectation."""
    entry = (registry.get("families") or {}).get(str(family))
    if entry is None:
        entry = registry.get("default") or dict(allowed=[], mode="unbound")
        return dict(family=str(family), mode=entry.get("mode", "unbound"), allowed=[],
                    source="declared default", declared_family=False)
    return dict(family=str(family), mode=entry["mode"], allowed=list(entry["allowed"]),
                source="kuhul://targets/v1", declared_family=True)


def context(binding_record: dict) -> dict:
    """The typed context handed to the model. A deterministic binding is stated as resolved, not offered."""
    return dict(schema_uri="urn:kuhul:schema:binding-context:v1",
                allowed_targets=list(binding_record["allowed"]),
                selection_mode=binding_record["mode"],
                resolved_target=(binding_record["allowed"][0]
                                 if binding_record["mode"] == "deterministic" else None),
                authority="proposal")


def check(binding_record: dict, proposal: dict) -> dict:
    """Ch'en's membership test. A conflicting target is kept, recorded and refused - never rewritten."""
    raw = proposal.get("target")
    allowed = list(binding_record["allowed"])
    mode = binding_record["mode"]
    if mode == "unbound":
        return dict(ok=True, skipped=True, mode=mode, raw_target=raw, resolved_target=None,
                    conflict=False, reason="this family binds no target")
    if binding_record.get("resolved_target") and raw and raw != binding_record["resolved_target"]:
        return dict(ok=False, conflict=True, mode=mode, raw_target=raw,
                    resolved_target=binding_record["resolved_target"], admitted=False,
                    reason=f"the model proposed {raw!r} where Wo resolved "
                           f"{binding_record['resolved_target']!r}; the proposal is rejected, not rewritten")
    if raw is None:
        return dict(ok=False, conflict=False, mode=mode, raw_target=None,
                    resolved_target=(allowed[0] if mode == "deterministic" else None),
                    admitted=False, reason="no target was proposed")
    if raw not in allowed:
        return dict(ok=False, conflict=True, mode=mode, raw_target=raw, resolved_target=None,
                    admitted=False,
                    reason=f"{raw!r} is registered but not authorized for this family "
                           f"(allowed: {', '.join(allowed) or 'none'})")
    return dict(ok=True, conflict=False, mode=mode, raw_target=raw, resolved_target=raw,
                admitted=False, reason=None)


def evidence(binding_record: dict, proposal: dict, verdict: dict) -> dict:
    """Both targets, always: the raw model choice and what Wo bound, with the conflict flag."""
    return dict(schema="kuhul://evidence/binding/v1", family=binding_record.get("family"),
                mode=binding_record.get("mode"), allowed=list(binding_record.get("allowed") or []),
                raw_target=proposal.get("target"), resolved_target=verdict.get("resolved_target"),
                conflict=bool(verdict.get("conflict")), accepted=bool(verdict.get("ok")
                                                                      and not verdict.get("skipped")),
                reason=verdict.get("reason"), admitted=False, authority="declaration_only",
                target_source=("missing" if proposal.get("target") is None else
                               "wo_resolved" if (binding_record.get("resolved_target")
                                                 and proposal.get("target")
                                                 == binding_record["resolved_target"]
                                                 and binding_record.get("mode") == "deterministic"
                                                 and False) else "model_proposed"))


def summary(registry: dict) -> str:
    if not registry["ok"]:
        lines = ["target registry · INVALID"]
        lines += [f"  {problem['code']}: {problem['detail']}" for problem in registry["problems"]]
        return "\n".join(lines)
    lines = [f"target registry · {len(registry['families'])} famil(ies)"]
    for name, entry in sorted(registry["families"].items()):
        lines.append(f"  {name:22} {entry['mode']:13} {', '.join(entry['allowed']) or '(none)'}")
    return "\n".join(lines)
