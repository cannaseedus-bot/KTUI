"""Operator composition as a graph, with the host resolving edges — but never repairing a plan.

A small model is good at *naming* operators and bad at *chaining* them: the measured failure was a plan
whose operators were all valid while its `next` fields did not connect. So the model may propose nodes and
the host resolves the edges:

    {"phase": "Sek", "operators": ["filter", "map", "fold", "reduce"], "authority": "proposal"}

What the host must **not** do is silently repair a wrong plan. If the task needs `filter -> map` and the
plan carries four operators, the result says `extra_operators`; it does not trim the plan and call it valid.

The canonical form encodes the contract already established: `accumulate` is the state update *inside*
`fold`, not a standalone step that replaces it.

        filter -> map -> fold -> reduce
                            |
                            +-> accumulate (nested)

So `compare()` reports four separate facts - nodes, edges, order, authority - because a model can get the
operator set right and the connections wrong, which is precisely what the 1B model did.
"""
from __future__ import annotations

CANONICAL = ("filter", "map", "fold", "reduce")
NESTED = {"accumulate": "fold"}
OPERATORS = ("filter", "map", "fold", "accumulate", "reduce")
PHASES = ("Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul")
PHASE_ALIASES = {"pop": "Pop", "wo": "Wo", "yax": "Yax", "sek": "Sek", "chen": "Ch'en",
                 "ch'en": "Ch'en", "xul": "Xul"}
AUTHORITIES = ("proposal", "declaration_only")


def canonical_graph(operators=CANONICAL) -> dict:
    """The declared graph: an ordered chain with nested children rather than a flat list."""
    nodes = [dict(id=f"{operator}#0", operator=operator, parent=None) for operator in operators]
    edges = [[nodes[index]["id"], nodes[index + 1]["id"]] for index in range(len(nodes) - 1)]
    for child, parent in NESTED.items():
        if parent in operators:
            parent_node = f"{parent}#0"
            nodes.append(dict(id=f"{child}#0", operator=child, parent=parent_node))
            edges.append([parent_node, f"{child}#0"])
    return dict(nodes=nodes, edges=edges, operators=list(operators),
                nested=dict(NESTED))


def normalise(operators: list) -> dict:
    """Split a proposed sequence into top-level steps and nested updates, preserving order."""
    top: list[str] = []
    nested: list[str] = []
    unknown: list[str] = []
    for operator in operators or []:
        name = str(operator or "").strip().lower()
        if name in NESTED:
            nested.append(name)
        elif name in OPERATORS:
            top.append(name)
        else:
            unknown.append(str(operator))
    return dict(top=top, nested=nested, unknown=unknown)


def validate_sequence(proposed: dict) -> dict:
    """Validate the *node* proposal: a phase, registered operators, and a proposal authority."""
    problems: list[dict] = []
    if not isinstance(proposed, dict):
        return dict(ok=False, problems=[dict(code="shape", detail="a plan must be an object")])
    phase = PHASE_ALIASES.get(str(proposed.get("phase") or "").strip().lower())
    if phase is None:
        problems.append(dict(code="phase", detail=f"unknown phase {proposed.get('phase')!r}"))
    operators = proposed.get("operators")
    if not isinstance(operators, list) or not operators:
        problems.append(dict(code="operators", detail="operators must be a non-empty list"))
        operators = []
    authority = str(proposed.get("authority") or "").strip().lower()
    if authority not in AUTHORITIES:
        problems.append(dict(code="authority", detail=f"authority {authority!r}"))
    parts = normalise(operators)
    if parts["unknown"]:
        problems.append(dict(code="operator", detail=f"unregistered operators {parts['unknown']}"))
    if not parts["top"]:
        problems.append(dict(code="operators", detail="no top-level operator remains after nesting"))
    if parts["nested"] and parts["nested"] != list(NESTED)[:len(parts["nested"])]:
        problems.append(dict(code="nested", detail=f"unexpected nested set {parts['nested']}"))
    return dict(ok=not problems, problems=problems, phase=phase, authority=authority,
                operators=list(parts["top"]), nested=list(parts["nested"]),
                authority_state="declaration_only", execution=False)


def compare(proposed: list | dict, *, expected=CANONICAL) -> dict:
    """Score a plan against the canonical graph: nodes, edges, order, authority - separately.

    The host normalises representation (a nested `accumulate` is attached to `fold`) but never adds a
    step the model did not propose, so a short plan stays short and an over-long one is reported as
    `extra_operators` rather than trimmed into a pass.
    """
    from collections import Counter

    problems: list[dict] = []
    authority_ok: bool | None = None
    phase: str | None = None
    if isinstance(proposed, dict):
        phase = PHASE_ALIASES.get(str(proposed.get("phase") or "").strip().lower())
        if phase is None:
            problems.append(dict(code="phase", detail=f"unknown phase {proposed.get('phase')!r}"))
        authority = str(proposed.get("authority") or "").strip().lower()
        authority_ok = authority in AUTHORITIES
        if not authority_ok:
            problems.append(dict(code="authority", detail=f"authority {authority!r}"))
        raw = proposed.get("operators") if isinstance(proposed.get("operators"), list) else []
    else:
        raw = list(proposed or [])
    parts = normalise(raw)
    if parts["unknown"]:
        problems.append(dict(code="operator", detail=f"unregistered operators {parts['unknown']}"))
    operators = list(parts["top"])
    expected_parts = normalise(list(expected))
    expected_top = list(expected_parts["top"])

    counts, expected_counts = Counter(operators), Counter(expected_top)
    extra = sorted((counts - expected_counts).elements())
    missing = sorted((expected_counts - counts).elements())
    # A nested operator proposed without its parent is a contract violation, not a missing step.
    misplaced = [name for name in parts["nested"] if NESTED[name] not in operators]
    nodes_ok = not extra and not missing
    edges_ok = operators == expected_top
    verdict = ("exact" if nodes_ok and edges_ok else
               "extra_operators" if extra else
               "missing_operators" if missing else
               "wrong_order")
    if misplaced:
        verdict = "misplaced_accumulate"
    return dict(schema="kuhul-plan-graph/1", phase=phase, proposed=operators,
                proposed_nested=list(parts["nested"]), expected=expected_top,
                nodes_ok=nodes_ok, edges_ok=edges_ok,
                extra_operators=extra, missing_operators=missing,
                misplaced_accumulate=misplaced, authority_ok=authority_ok,
                verdict=verdict, problems=problems,
                canonical=canonical_graph(expected_top or CANONICAL),
                authority_state="declaration_only", execution=False,
                note="the host resolves edges; it does not add or trim steps to make a plan valid")


def parse_sequence(text: str) -> dict | None:
    """Extract a node proposal from a model reply, tolerating fences and surrounding prose."""
    import json
    import re

    body = re.sub(r"^```(?:json)?|```$", "", str(text or "").strip(), flags=re.M).strip()
    for opening, closing in (("{", "}"), ("[", "]")):
        start, end = body.find(opening), body.rfind(closing)
        if start == -1 or end <= start:
            continue
        try:
            parsed = json.loads(body[start:end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "operators" in parsed:
            return parsed
        if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
            return dict(phase="Sek", operators=parsed, authority="proposal")
    return None
