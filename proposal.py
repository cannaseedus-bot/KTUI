"""Operation proposals: the small, checkable thing a model should produce instead of code.

The idea from the architecture: a model does not have to write a program, only to name the phase, the
operator, the target, the binding, what comes next, and that it is a proposal. The host then decides.

    {"phase": "Sek", "operator": "filter", "target": "graph.matches",
     "binding": "valid", "next": "map", "authority": "proposal"}

Validation is the whole value: an unknown phase, an unknown operator, an operator that needs a binding
without one, a target whose scheme is not registered, a `next` that is not a phase, or an authority
claim other than `proposal`/`declaration_only` - all refused with a reason.

A valid proposal is still not an admitted operation. `validate()` returns `admitted: false` always, and
`to_program()` only turns accepted proposals into declarative source, which is then checked by the
program layer in its own right.
"""
from __future__ import annotations

import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import program  # noqa: E402

SCHEMA = "kuhul.operation-proposal/1"
PHASES = ("Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul")
PHASE_ALIASES = {"pop": "Pop", "wo": "Wo", "yax": "Yax", "sek": "Sek", "chen": "Ch'en",
                 "ch'en": "Ch'en", "xul": "Xul"}
OPERATORS = ("filter", "map", "fold", "accumulate", "reduce")
AUTHORITIES = ("proposal", "declaration_only")
# Where an operator *naturally* belongs. Not a rule - the architecture is explicit that a phase may use
# an operator for its own purposes - so a mismatch is a notice, never a refusal.
HOME_PHASE = {"filter": ("Yax", "Sek", "Ch'en"), "map": ("Yax", "Sek"), "fold": ("Sek",),
              "accumulate": ("Sek",), "reduce": ("Sek", "Ch'en")}
NEEDS_BINDING = ("filter", "map")
REGISTERED_SCHEMES = ("kuhul://", "aiml://", "gml://", "srai://", "micronaut://", "graph.",
                      "lane.", "⟁")


def _phase(value) -> str | None:
    return PHASE_ALIASES.get(str(value or "").strip().lower())


def _target_ok(target: str) -> bool:
    text = str(target or "").strip()
    if not text:
        return False
    if text.startswith(REGISTERED_SCHEMES):
        return True
    return bool(__import__("re").fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", text))


def validate(proposal: dict) -> dict:
    """Check one proposal against the declared vocabulary. Never admits, never executes."""
    problems: list[dict] = []
    notices: list[dict] = []
    if not isinstance(proposal, dict):
        return dict(schema=SCHEMA, ok=False, admitted=False,
                    problems=[dict(code="shape", detail="a proposal must be an object")])
    phase = _phase(proposal.get("phase"))
    operator = str(proposal.get("operator") or "").strip().lower()
    target = str(proposal.get("target") or "").strip()
    binding = proposal.get("binding")
    next_step = proposal.get("next")
    authority = str(proposal.get("authority") or "").strip().lower()

    if phase is None:
        problems.append(dict(code="phase", detail=f"unknown phase {proposal.get('phase')!r}"))
    if operator not in OPERATORS:
        problems.append(dict(code="operator", detail=f"unknown operator {proposal.get('operator')!r}"))
    if not _target_ok(target):
        problems.append(dict(code="target", detail=f"target {target!r} is not a registered reference"))
    if operator in NEEDS_BINDING and not (isinstance(binding, str) and binding.strip()):
        problems.append(dict(code="binding", detail=f"{operator} requires a binding"))
    if binding is not None and not isinstance(binding, str):
        problems.append(dict(code="binding_type", detail="binding must be a string"))
    # `next` names the next step of the plan, which may be an operator (FILTER -> MAP) or a phase
    # (Sek -> Ch'en); the review's table uses the operator form.
    next_value = str(next_step or "").strip().lower()
    if next_step is not None and _phase(next_step) is None and next_value not in OPERATORS:
        problems.append(dict(code="next",
                             detail=f"next {next_step!r} is neither a phase nor an operator"))
    if authority not in AUTHORITIES:
        problems.append(dict(code="authority",
                             detail=f"authority {authority!r} is not one of {', '.join(AUTHORITIES)}"))
    if phase is not None and operator in OPERATORS and phase not in HOME_PHASE.get(operator, ()):
        notices.append(dict(code="unusual_phase",
                            detail=f"{operator} usually lives in {', '.join(HOME_PHASE[operator])}, "
                                   f"not {phase}"))
    return dict(schema=SCHEMA, ok=not problems, admitted=False, problems=problems, notices=notices,
                proposal=dict(phase=phase, operator=operator, target=target,
                              binding=binding if isinstance(binding, str) else None,
                              next=(_phase(next_step) or next_value) if next_step else None,
                              authority=authority or None),
                authority="declaration_only", execution=False, mutation=False)


def validate_all(proposals: list) -> dict:
    """Validate a sequence: each proposal, plus the chain its `next` fields describe."""
    results = [validate(proposal) for proposal in proposals or []]
    problems = [dict(code="invalid_proposal", detail=f"#{index}", problems=result["problems"])
                for index, result in enumerate(results) if not result["ok"]]
    ok = not problems
    order = [result["proposal"]["phase"] for result in results
             if result["ok"] and result["proposal"]["phase"]]
    for index, result in enumerate(results):
        if not result["ok"]:
            continue
        expected = result["proposal"]["next"]
        if expected is None:
            continue
        following = next(((later["proposal"]["phase"], later["proposal"]["operator"])
                          for later in results[index + 1:] if later["ok"]), None)
        if following is None:
            continue
        phase, operator = following
        if expected not in (phase, operator):
            problems.append(dict(code="chain_mismatch",
                                 detail=f"#{index} says next {expected}, but the next step is "
                                        f"{phase}/{operator}"))
            ok = False
    return dict(schema=SCHEMA, ok=ok, admitted=False, problems=problems, results=results,
                phases=order, notices=[notice for result in results
                                       for notice in result.get("notices") or []],
                authority="declaration_only", execution=False)


def to_program(proposals: list) -> str:
    """Turn accepted proposals into declarative K'UHUL source (checked again by the program layer)."""
    accepted = [result for result in validate_all(proposals)["results"] if result["ok"]]
    blocks: dict[str, list[str]] = {}
    for result in accepted:
        spec = result["proposal"]
        # Targets and bindings are references, not lane names, so they are emitted as strings: the
        # program layer is strict about bare identifiers and should stay that way.
        parts = [f'"{spec["target"]}"']
        if spec["operator"] in NEEDS_BINDING and spec["binding"]:
            parts.append(f'"{spec["binding"]}"')
        args = ", ".join(parts)
        blocks.setdefault(spec["phase"], []).append(f"{spec['operator']}({args})")
    lines = []
    for phase in PHASES:
        if phase in blocks:
            lines.append(f"{phase} {{")
            lines += [f"  {line}" for line in blocks[phase]]
            lines.append("}")
    return "\n".join(lines) + "\n" if lines else ""


def plan(proposals: list) -> dict:
    """Validate, convert, and validate the conversion - the host's check of a model's proposal."""
    report = validate_all(proposals)
    source = to_program(proposals) if report["ok"] else ""
    parsed = None
    program_report = None
    if source:
        try:
            parsed = program.parse(source)
            program_report = program.validate(parsed)
        except program.ProgramError as error:
            program_report = dict(ok=False, problems=[dict(code="parse", detail=str(error))])
    return dict(schema=SCHEMA, ok=bool(report["ok"] and (program_report or {}).get("ok", False)),
                admitted=False, proposals=report, source=source,
                program=program_report, authority="declaration_only",
                execution=False, mutation=False)


def summary(report: dict) -> str:
    if "proposals" in report:
        inner = report["proposals"]
        lines = [f"proposal set · {len(inner['results'])} proposal(s) · "
                 f"{'valid' if report['ok'] else 'REJECTED'}"]
        for problem in inner["problems"][:6]:
            lines.append(f"  {problem['code']}: {problem['detail']}")
        if report["source"]:
            lines.append("  source:")
            lines.extend(f"    {line}" for line in report["source"].splitlines())
        lines.append("  (admitted: false · declaration_only)")
        return "\n".join(lines)
    lines = [f"proposal · {'ok' if report['ok'] else 'REJECTED'}"]
    for problem in report["problems"]:
        lines.append(f"  {problem['code']}: {problem['detail']}")
    lines.append("  (admitted: false · declaration_only)")
    return "\n".join(lines)
