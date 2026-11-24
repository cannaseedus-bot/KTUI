"""The five operators, and a URI resolver that navigates without granting anything.

Two halves of the same idea, and the same rule applies to both: they compute and they navigate, but
they never decide authority.

**Operators** - FILTER, MAP, FOLD (+ ACCUMULATE inside it), REDUCE - with the rank distinction the
architecture turns on:

    FILTER      n candidates -> m candidates      same shape, fewer items
    MAP         candidate -> proposition          one in, one out, typed
    FOLD        sequence -> accumulator           rank preserved (a matrix stays a matrix)
    ACCUMULATE  inside a fold: update that state  rank preserved
    REDUCE      collection -> scalar/summary      rank changes, along a declared axis

**URI resolution** - `micronaut://`, `kuhul://phases/…`, `aiml://…`, `srai://…`, `gml://…` - returns
typed data with provenance. A URI that resolves grants nothing: every envelope says
`authority: "declaration_only"`, `execution: false`, and the resolver refuses unknown schemes, cycles,
and anything over its depth or budget.

Nothing here executes an operation the host has not already granted.
"""
from __future__ import annotations

import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

import aiml_graph  # noqa: E402
import phase_manifest  # noqa: E402
import user_memory  # noqa: E402

SCHEMA = "kuhul.operators/1"
RANK = {"filter": "preserved", "map": "preserved", "fold": "preserved",
        "accumulate": "preserved", "reduce": "collapsed"}
DEFAULT_BUDGET = dict(max_items=500, max_depth=6, max_nodes=200)


class OperatorError(ValueError):
    """An operator applied to data of the wrong shape."""


def _provenance(stage: str, before: int, after: int, **extra) -> dict:
    return dict(operator=stage, rank=RANK[stage], count_before=before, count_after=after, **extra)


# -- operators ---------------------------------------------------------------------------------------
def apply_filter(items: list, keep, *, label: str = "filter") -> dict:
    """Keep items for which `keep(item)` is true. Pure: the input list is untouched."""
    items = list(items)
    kept, dropped = [], []
    for item in items:
        (kept if keep(item) else dropped).append(item)
    return dict(value=kept, dropped=dropped, provenance=_provenance("filter", len(items), len(kept),
                                                                   label=label, dropped=len(dropped)))


def apply_map(items: list, transform, *, label: str = "map") -> dict:
    """Transform every item into a typed proposition; the count must not change."""
    items = list(items)
    # One in, one out, by construction: a transform cannot silently change the collection size, which
    # is what keeps MAP rank-preserving and FILTER the only size-changing stage.
    mapped = [transform(item) for item in items]
    return dict(value=mapped, provenance=_provenance("map", len(items), len(mapped), label=label))


def accumulate(state: dict, item, *, key: str = "items") -> dict:
    """The state update used *inside* a fold: append and count, rank preserved."""
    updated = dict(state)
    updated.setdefault(key, []).append(item)
    updated["count"] = updated.get("count", 0) + 1
    return updated


def apply_fold(items: list, accumulate_fn, initial: dict, *, label: str = "fold") -> dict:
    """Fold a sequence into an accumulator. Rank preserved: a 2-D state stays 2-D."""
    items = list(items)
    state = dict(initial)
    for item in items:
        state = accumulate_fn(state, item)
    shape = state.get("shape") or ("vector" if state.get("items") else "scalar")
    return dict(value=state,
                provenance=_provenance("fold", len(items), int(state.get("count", len(items))),
                                       label=label, shape=shape))


def apply_reduce(items: list, *, axis: str = "score", mode: str = "max", label: str = "reduce") -> dict:
    """Collapse a collection to one value along a declared axis. Rank changes - that is the point."""
    items = list(items)
    if not items:
        return dict(value=None, provenance=_provenance("reduce", 0, 0, label=label, axis=axis,
                                                       mode=mode, note="nothing to reduce"))
    values = [item.get(axis) if isinstance(item, dict) else None for item in items]
    try:
        if mode == "max":
            winner = max(range(len(items)), key=lambda index: (values[index] is not None,
                                                               values[index] or 0))
        elif mode == "min":
            winner = min(range(len(items)), key=lambda index: (values[index] is None,
                                                               values[index] or 0))
        elif mode == "sum":
            total = sum(value for value in values if isinstance(value, (int, float)))
            return dict(value=dict(axis=axis, total=round(total, 6), items=len(items)),
                        provenance=_provenance("reduce", len(items), 1, label=label, axis=axis,
                                               mode=mode))
        else:
            raise OperatorError(f"unknown reduce mode {mode!r}")
    except TypeError as error:
        raise OperatorError(f"axis {axis!r} is not ordered: {error}") from error
    return dict(value=dict(axis=axis, mode=mode, selected=items[winner],
                           value=values[winner], rank=winner),
                provenance=_provenance("reduce", len(items), 1, label=label, axis=axis, mode=mode))


def pipeline(candidates: list, *, keep=None, transform=None, accumulator=None, axis="score",
             mode="max", budget: int = DEFAULT_BUDGET["max_items"]) -> dict:
    """FILTER -> MAP -> FOLD(+ACCUMULATE) -> REDUCE over one candidate set.

    Returns the evidence-bearing result: the selected proposal, the accumulated state, and the
    provenance of every stage, including which candidates were dropped and why.
    """
    candidates = list(candidates)
    if len(candidates) > budget:
        candidates = candidates[:budget]
    trace = []
    current = candidates
    if keep is not None:
        filtered = apply_filter(current, keep, label="compatibility")
        trace.append(filtered["provenance"])
        current = filtered["value"]
    if transform is not None:
        mapped = apply_map(current, transform)
        trace.append(mapped["provenance"])
        current = mapped["value"]
    folded = apply_fold(current, accumulator or accumulate, dict(items=[], count=0), label="evidence")
    trace.append(folded["provenance"])
    reduced = apply_reduce(current, axis=axis, mode=mode, label="ranking")
    trace.append(reduced["provenance"])
    return dict(schema=SCHEMA, stages=trace, evidence=folded["value"], selected=reduced["value"],
                candidates_in=len(candidates), candidates_kept=len(current),
                execution=False, mutation=False, authority="declaration_only")


# -- URI resolution ----------------------------------------------------------------------------------
def _phases(uri: str) -> list[dict]:
    name = uri[len("kuhul://phases/"):].strip("/")
    path = PACKAGE / "phases" / "json" / f"{name}.json"
    if not name or not path.is_file():
        raise OperatorError(f"no manifest for phase {name!r}")
    loaded = phase_manifest.load(path, root=PACKAGE / "phases" / "json", check_files=False)
    if not loaded["ok"]:
        raise OperatorError("; ".join(problem["detail"] for problem in loaded["problems"]))
    return [loaded["manifest"]]


def _aiml(uri: str) -> list[dict]:
    ref = uri[len("aiml://"):]
    graph, _, node = ref.partition("#")
    return [dict(ref=uri, graph=graph, node=node or None,
                 note="a node reference; resolving it does not evaluate the category")]


def _gml(uri: str) -> list[dict]:
    graph_id = uri[len("gml://"):]
    return [dict(ref=uri, graph_id=graph_id,
                 note="a whole-graph reference; the projection is built per user, not per uri")]


def _micronaut(uri: str) -> list[dict]:
    return [dict(ref=uri, endpoint="v1/chat", transport="http://127.0.0.1:8756/v1/chat",
                 note="the daemon endpoint; a request is still the host's to admit")]


SCHEMES = {"kuhul://phases/": _phases, "aiml://": _aiml, "gml://": _gml, "micronaut://": _micronaut,
           "srai://": lambda uri: [dict(ref=uri, note="an srai route name; the resolver owns routing")]}


def resolve_uri(uri: str, *, depth: int = 0, budget: dict | None = None,
                seen: set | None = None) -> dict:
    """Resolve one URI to typed data with provenance. Never authority, never execution."""
    budget = dict(DEFAULT_BUDGET, **(budget or {}))
    seen = set() if seen is None else seen
    uri = str(uri or "").strip()
    envelope = dict(schema=SCHEMA, uri=uri, ok=False, kind=None, data=[], chain=[],
                    authority="declaration_only", execution=False, mutation=False,
                    depth=depth)
    if not uri:
        return dict(envelope, error="empty uri")
    if depth > budget["max_depth"]:
        return dict(envelope, error=f"depth limit {budget['max_depth']} exceeded")
    if uri in seen:
        return dict(envelope, error=f"cycle: {uri!r} was already resolved in this chain")
    scheme = next((prefix for prefix in SCHEMES if uri.startswith(prefix)), None)
    if scheme is None:
        return dict(envelope, error=f"unregistered uri scheme in {uri!r}")
    seen = seen | {uri}
    try:
        data = SCHEMES[scheme](uri)
    except OperatorError as error:
        return dict(envelope, error=str(error), kind=scheme.rstrip("/:"))
    if len(data) > budget["max_nodes"]:
        return dict(envelope, error=f"node budget {budget['max_nodes']} exceeded",
                    kind=scheme.rstrip("/:"))
    return dict(envelope, ok=True, kind=scheme.rstrip("/:"), data=data, chain=[uri],
                resolved=data[0] if data else None)


def walk(uris: list[str], *, budget: dict | None = None) -> dict:
    """Resolve a chain of URIs, carrying the provenance and stopping on the first refusal."""
    budget = dict(DEFAULT_BUDGET, **(budget or {}))
    seen: set = set()
    results = []
    for index, uri in enumerate(uris):
        if index >= budget["max_items"]:
            results.append(dict(uri=uri, ok=False, error="item budget exceeded"))
            break
        result = resolve_uri(uri, depth=index, budget=budget, seen=seen)
        results.append(result)
        seen = seen | {uri}
        if not result["ok"]:
            break
    return dict(schema=SCHEMA, chain=[result["uri"] for result in results],
                resolved=[result for result in results if result["ok"]],
                refused=[result for result in results if not result["ok"]],
                ok=all(result["ok"] for result in results),
                authority="declaration_only", execution=False, mutation=False,
                note="a chain of references; the host decides what may run")


def summary(result: dict) -> str:
    if "uri" in result:
        status = "ok" if result["ok"] else f"refused ({result.get('error')})"
        return f"{result['uri']} -> {result.get('kind')} · {status} · declaration_only"
    lines = [f"uri chain · {len(result['chain'])} link(s) · "
             f"{'ok' if result['ok'] else 'stopped'}"]
    for item in result["resolved"]:
        lines.append(f"  {item['uri']} -> {item['kind']}")
    for item in result["refused"]:
        lines.append(f"  {item['uri']} -> refused: {item['error']}")
    return "\n".join(lines)
