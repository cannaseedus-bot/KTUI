"""Host adapter for the AIML/GML six-contract bundle: declarations in, proposals out, no authority.

Four invariants, each with a guard in `tests_host/test_aiml_bundle_host.py`:

1. **No independent AIML compiler.** This module imports the package's `aiml_bundle.Bundle` and its
   resolvers. It does not re-implement pattern matching: a proposal names a node by reference and
   resolves it through the graph. Text matching stays where it belongs (the python-aiml kernel).
2. **No authority from declarations.** A proposal carries `authorized: False` and `persistence: None`
   no matter what the document says; `admit()` reports `executes: False`. A forged proposal that
   claims authority is refused, not honoured.
3. **No direct database writes.** Nothing here opens a file for writing. Proposing and admitting are
   pure reads, and the guard hashes the memory log and task list either side to prove it.
4. **No bypass around the graph.** A category resolves through `pattern_ref`/`template_ref`; a
   foreign-scheme reference, a foreign schema or an unresolved node is a refusal.

Capabilities declared by the bundle are checked against a caller-supplied allowlist. Declaring
`requires [ capability "shell.exec" ]` in a GML document cannot authorize anything - it can only be
refused.
"""
from __future__ import annotations

import json
from pathlib import Path

import phases

APP_ROOT = Path(__file__).resolve().parent
CONTRACTS = phases.ROOT / "aiml_contracts"
EXTENSION_DOC = phases.ROOT / "schemas" / "aiml-registry.gml"
SCHEMA_ID = "aiml-gml/1"
MAX_SRAI_DEPTH = 4
PROPOSAL_SCHEMA = "kuhul.aiml-proposal/1"


class BundleRefused(ValueError):
    """A reference or document the host will not turn into a proposal."""


def _modules() -> dict:
    return dict(gml2=phases.core_module("gml2"),
                extension=phases.core_module("extension"),
                bundle=phases.core_module("aiml_bundle"),
                resolvers=phases.core_module("resolvers"))


def contracts(folder: Path = CONTRACTS) -> dict:
    """The six contract documents, keyed by `<stem>/main` as the bundle expects."""
    gml2 = phases.core_module("gml2")
    return {f"{path.stem}/main": gml2.parse(path.read_text(encoding="utf-8"))
            for path in sorted(Path(folder).glob("*.gml"))}


def load(folder: Path = CONTRACTS, extension_doc: Path = EXTENSION_DOC) -> tuple[object, list[dict]]:
    """The bundle and anything that went wrong loading it. Never raises for a bad document."""
    try:
        modules = _modules()
        extension = modules["extension"].load_extension(modules["gml2"].parse(
            Path(extension_doc).read_text(encoding="utf-8")))
        return modules["bundle"].Bundle(contracts(folder), extension), []
    except Exception as error:
        return None, [dict(code="load_failed", detail=f"{type(error).__name__}: {error}"[:300])]


def validate(folder: Path = CONTRACTS) -> dict:
    bundle, problems = load(folder)
    if bundle is None:
        return dict(ok=False, state="NOT_LOADED", contracts=[], problems=problems)
    try:
        state = bundle.validate()
        problems = []
    except Exception as error:
        state = "REJECTED"
        problems = [dict(code="validation_failed", detail=f"{type(error).__name__}: {error}"[:300])]
    names = sorted(bundle.graphs)
    return dict(ok=state == "BINDINGS_VALIDATED", state=state, contracts=names, problems=problems)


def _attr(node, name, default=None):
    for entry in getattr(node, "entries", []) or []:
        if getattr(entry, "name", "") == name:
            return entry.value
    return default


def _capabilities(node) -> list[str]:
    found = []
    for entry in getattr(node, "entries", []) or []:
        if getattr(entry, "name", "") == "requires":
            capability = _attr(entry.value, "capability")
            if isinstance(capability, str):
                found.append(capability)
    return sorted(found)


def _graph_and_id(ref: str) -> tuple[str, int]:
    tail = ref.split("://", 1)[-1]
    gid, _, fragment = tail.partition("#")
    try:
        return gid, int(fragment)
    except ValueError as error:
        raise BundleRefused(f"reference {ref!r} has no node id") from error


def propose(ref: str, folder: Path = CONTRACTS) -> dict:
    """Resolve one node into a read-only proposal. Raises BundleRefused for anything unresolvable."""
    report = validate(folder)
    if not report["ok"]:
        raise BundleRefused(f"the bundle does not validate ({report['state']})")
    bundle, _ = load(folder)
    modules = _modules()
    try:
        node = modules["resolvers"].resolve(ref, bundle.graphs, expected="node_addressable",
                                            expected_schema=SCHEMA_ID)
    except Exception as error:
        # Foreign scheme, foreign schema, or an unresolved node: never silently tolerated.
        raise BundleRefused(f"{type(error).__name__}: {error}") from error

    gid, node_id = _graph_and_id(ref)
    document = bundle.graphs.get(gid)
    if document is None:
        raise BundleRefused(f"graph {gid!r} is not in the bundle")
    kind = _attr(node, "kind")
    proposal = dict(schema=PROPOSAL_SCHEMA, ref=ref, graph=gid, node_id=node_id, kind=kind,
                    contract=_attr(document, "contract"), capabilities=_capabilities(node),
                    srai=[], template=None, pattern=None, authorized=False, persistence=None,
                    bundle_state=report["state"])

    if kind == "category":
        for key, target in (("pattern_ref", "pattern"), ("template_ref", "template")):
            reference = _attr(node, key)
            if not isinstance(reference, str):
                raise BundleRefused(f"category {ref!r} has no {key}")
            try:
                bound = modules["resolvers"].resolve(reference, bundle.graphs,
                                                     expected="node_addressable",
                                                     expected_schema=SCHEMA_ID)
            except Exception as error:
                raise BundleRefused(f"{key} {reference!r}: {type(error).__name__}: {error}") from error
            if target == "pattern":
                proposal["pattern"] = dict(expression=_attr(bound, "expression"),
                                           wildcard_count=_attr(bound, "wildcard_count"))
            else:
                segments = [(_attr(segment.value, "ordinal"), _attr(segment.value, "kind"))
                            for segment in (getattr(bound, "entries", []) or [])
                            if getattr(segment, "name", "") == "segment"]
                proposal["template"] = dict(segments=[dict(ordinal=item[0], kind=item[1])
                                                      for item in segments])
            proposal["capabilities"] = sorted(set(proposal["capabilities"]) | set(_capabilities(bound)))
        # The redirect chain, in graph order, bounded: no traversal beyond the declared depth.
        chain = []
        for edge in getattr(document, "entries", []) or []:
            if getattr(edge, "name", "") != "edge":
                continue
            verb = _attr(edge.value, "verb")
            source = _attr(edge.value, "source")
            if verb == "@redirects_to" and source == node_id:
                chain.append(_attr(edge.value, "target_ref") or _attr(edge.value, "target"))
        proposal["srai"] = [item for item in chain if item is not None][:MAX_SRAI_DEPTH]
    elif kind == "srai":
        proposal["pattern"] = dict(expression=_attr(node, "expression"),
                                   wildcard_count=_attr(node, "wildcard_count"))
    return proposal


def canonical(proposal: dict) -> bytes:
    return json.dumps(proposal, sort_keys=True, separators=(",", ":")).encode("utf-8")


def admit(proposal: dict, allowlist: tuple[str, ...] = ()) -> dict:
    """Decide whether a proposal may be *used*. It never executes and never persists anything."""
    reasons: list[dict] = []
    if not isinstance(proposal, dict):
        return dict(admitted=False, executes=False, persistence=None,
                    reasons=[dict(code="not_a_proposal", detail=repr(type(proposal).__name__))])
    if proposal.get("bundle_state") != "BINDINGS_VALIDATED":
        reasons.append(dict(code="stale_bundle",
                            detail=f"bundle state {proposal.get('bundle_state')!r}"))
    if proposal.get("authorized"):
        reasons.append(dict(code="forged_authority",
                            detail="a proposal may not claim authority; the host decides, and it says no"))
    if len(proposal.get("srai") or []) > MAX_SRAI_DEPTH:
        reasons.append(dict(code="srai_depth_exceeded",
                            detail=f"{len(proposal['srai'])} redirects > {MAX_SRAI_DEPTH}"))
    allowed = set(allowlist)
    for capability in proposal.get("capabilities") or []:
        if capability not in allowed:
            reasons.append(dict(code="capability_not_allowed",
                                detail=f"{capability!r} is declared by the document but not authorized here"))
    return dict(admitted=not reasons, executes=False, persistence=None, authority="host",
                reasons=reasons or [dict(code="read_only_proposal",
                                         detail="declarations propose; the host authorizes; nothing runs")])


def summary(folder: Path = CONTRACTS) -> str:
    report = validate(folder)
    lines = [f"AIML bundle: {report['state']} · {len(report['contracts'])} contract(s)"]
    for name in report["contracts"]:
        lines.append(f"  {name}")
    for problem in report["problems"]:
        lines.append(f"  {problem['code']}: {problem['detail']}")
    lines.append("")
    lines.append("Declarations propose; the host authorizes; nothing in a GML document can execute.")
    return "\n".join(lines)
