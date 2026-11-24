"""The micronaut registry: typed agents, typed edges, and three independent guarantees.

The registry unifies what was scattered - phase manifests, AIML/SRAI declarations, GML references, REST
routes - under one lookup: which capabilities exist, what they accept and produce, and which hand-offs
are *declared*.

Three guarantees are reported separately, because each can fail without the others:

    structural   the payload's schema is a declared output of a registered micronaut
    routing      a declared edge accepts that schema, and (if given) leaves the declared source
    authority    the caller holds the edge's capability - an engine grant is not a caller grant

A schema is a type, **not** a destination: a payload that names `$schema` and a `target` gets nowhere
unless an edge for that schema is declared and the caller is authorised. Admission stays with XCFE, so
`admitted` is always false here.

    SchemaCompatible and EdgeDeclared and CapabilityAuthorized and XCFEAdmitted
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

MICRONAUTS = PACKAGE / "data" / "micronauts.json"
EDGES = PACKAGE / "data" / "micronaut-edges.json"
SCHEMA = "micronaut-schema/v1"
EDGE_SCHEMA = "micronaut-edge/v1"
PHASES = ("Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul")
PHASE_ALIASES = {"pop": "Pop", "wo": "Wo", "yax": "Yax", "sek": "Sek", "chen": "Ch'en",
                 "ch'en": "Ch'en", "xul": "Xul"}
OPERATORS = ("filter", "map", "fold", "accumulate", "reduce")


class RegistryError(ValueError):
    """A registry document that contradicts its own contract."""


def _phase(uri: str) -> str | None:
    text = str(uri or "").strip()
    if not text.startswith("kuhul://phases/"):
        return None
    return PHASE_ALIASES.get(text[len("kuhul://phases/"):].strip("/").lower())


def load(micronauts: Path = MICRONAUTS, edges: Path = EDGES) -> dict:
    """Load and validate both documents: identity, contracts, dependencies and edges."""
    problems: list[dict] = []
    try:
        catalogue = json.loads(Path(micronauts).read_text(encoding="utf-8"))
        wiring = json.loads(Path(edges).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, problems=[dict(code="unreadable", detail=str(error))],
                    by_uri={}, list=[], edges=[], schemas={})

    if catalogue.get("schema") != SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}"))
    if wiring.get("schema") != EDGE_SCHEMA:
        problems.append(dict(code="edge_schema", detail=f"expected {EDGE_SCHEMA}"))
    for document, name in ((catalogue, "micronauts"), (wiring, "edges")):
        if document.get("authority") != "declaration_only":
            problems.append(dict(code="authority", detail=f"{name} must be declaration_only"))

    by_uri: dict[str, dict] = {}
    for entry in catalogue.get("micronauts") or []:
        uri = str(entry.get("uri") or "")
        if not uri.startswith("micronaut://"):
            problems.append(dict(code="uri", detail=f"{uri!r} is not a micronaut uri"))
            continue
        if uri in by_uri:
            problems.append(dict(code="duplicate_uri", detail=uri))
            continue
        phase = _phase(entry.get("entry"))
        if phase is None:
            problems.append(dict(code="entry", detail=f"{uri}: {entry.get('entry')!r} is not a phase"))
        for field in ("input_schema", "output_schema"):
            if not str(entry.get(field) or "").startswith("kuhul://schema/"):
                problems.append(dict(code=field, detail=f"{uri}: {entry.get(field)!r}"))
        operator_names = [str(name) for name in entry.get("operators") or []]
        unknown = [name for name in operator_names if name not in OPERATORS]
        if unknown:
            problems.append(dict(code="operators", detail=f"{uri}: {unknown}"))
        if not entry.get("capabilities"):
            problems.append(dict(code="capability", detail=f"{uri}: declares no capability"))
        if entry.get("authority") != "declaration_only":
            problems.append(dict(code="authority", detail=f"{uri} must be declaration_only"))
        by_uri[uri] = dict(uri=uri, role=entry.get("role"), entry=phase,
                           authority=entry.get("authority"),
                           input_schema=entry.get("input_schema"),
                           output_schema=entry.get("output_schema"),
                           dependencies=list(entry.get("dependencies") or []),
                           operators=operator_names,
                           capabilities=list(entry.get("capabilities") or []))

    for uri, entry in by_uri.items():
        for dependency in entry["dependencies"]:
            if dependency not in by_uri:
                problems.append(dict(code="dependency", detail=f"{uri} needs {dependency!r}"))
            elif dependency == uri:
                problems.append(dict(code="dependency_cycle", detail=uri))

    declared_edges = []
    for index, edge in enumerate(wiring.get("edges") or []):
        where = f"edge #{index}"
        source, target = by_uri.get(edge.get("from")), by_uri.get(edge.get("to"))
        if source is None or target is None:
            problems.append(dict(code="endpoint", detail=f"{where}: {edge.get('from')} -> {edge.get('to')}"))
            continue
        if edge.get("output_schema_uri") != source["output_schema"]:
            problems.append(dict(code="edge_output",
                                 detail=f"{where}: {edge.get('output_schema_uri')!r} is not "
                                        f"{source['uri']}'s output"))
        if edge.get("input_schema_uri") != target["input_schema"]:
            problems.append(dict(code="edge_input",
                                 detail=f"{where}: {edge.get('input_schema_uri')!r} is not "
                                        f"{target['uri']}'s input"))
        if edge.get("capability") not in source["capabilities"] + target["capabilities"]:
            problems.append(dict(code="edge_capability",
                                 detail=f"{where}: {edge.get('capability')!r} is not declared by either end"))
        if edge.get("authority") != "declaration_only":
            problems.append(dict(code="edge_authority", detail=f"{where} must be declaration_only"))
        declared_edges.append(dict(source=source["uri"], target=target["uri"],
                                   input_schema_uri=edge.get("input_schema_uri"),
                                   output_schema_uri=edge.get("output_schema_uri"),
                                   capability=edge.get("capability"),
                                   authority=edge.get("authority")))

    schemas: dict[str, dict] = {}
    for entry in by_uri.values():
        schemas.setdefault(entry["output_schema"], dict(produced_by=[], consumed_by=[]))
        schemas[entry["output_schema"]]["produced_by"].append(entry["uri"])
        schemas.setdefault(entry["input_schema"], dict(produced_by=[], consumed_by=[]))
        schemas[entry["input_schema"]]["consumed_by"].append(entry["uri"])
    for entry in schemas.values():
        entry["produced_by"].sort()
        entry["consumed_by"].sort()
    order = sorted(by_uri)
    return dict(ok=not problems, problems=problems, by_uri=by_uri, list=[by_uri[uri] for uri in order],
                edges=sorted(declared_edges, key=lambda edge: (edge["source"], edge["target"])),
                schemas=dict(sorted(schemas.items())), authority="declaration_only")


def describe(registry: dict, uri: str) -> dict | None:
    return registry["by_uri"].get(str(uri or ""))


def route(registry: dict, schema_uri: str, *, from_uri: str | None = None,
          granted: set | None = None) -> dict:
    """Hand a payload of one declared schema to the next agent - or refuse, with the reason.

    The three guarantees are independent: a structurally valid payload with no declared edge is not a
    route, and a declared edge the caller may not use is not an authorised transition.
    """
    granted = set(granted or ())
    schema_uri = str(schema_uri or "").strip()
    declaration = registry["schemas"].get(schema_uri)
    structural = declaration is not None and bool(declaration["produced_by"])
    edges = [edge for edge in registry["edges"]
             if edge["output_schema_uri"] == schema_uri
             and (from_uri is None or edge["source"] == from_uri)]
    routing = bool(edges)
    # XCFE admission is not decided here, ever.
    if not structural:
        return dict(schema="micronaut-route/1", schema_uri=schema_uri, from_uri=from_uri,
                    structural=False, routing=False, authority=False, admitted=False,
                    selected=None, candidates=[], refused="schema_not_declared",
                    reason="no registered micronaut produces that schema")
    if not routing:
        return dict(schema="micronaut-route/1", schema_uri=schema_uri, from_uri=from_uri,
                    structural=True, routing=False, authority=False, admitted=False,
                    selected=None, candidates=[], refused="no_declared_edge",
                    reason=("no declared edge accepts that schema from "
                            f"{from_uri or 'any source'}"))
    authorised, denied = [], []
    for edge in edges:
        (authorised if edge["capability"] in granted else denied).append(edge)
    if not authorised:
        return dict(schema="micronaut-route/1", schema_uri=schema_uri, from_uri=from_uri,
                    structural=True, routing=True, authority=False, admitted=False,
                    selected=None, candidates=[], denied=denied,
                    refused="capability_not_granted",
                    reason=f"the caller does not hold {denied[0]['capability']}")
    # Deterministic selection: declared order (source, target). Ambiguity is reported, not hidden.
    selected = authorised[0]
    return dict(schema="micronaut-route/1", schema_uri=schema_uri, from_uri=from_uri,
                structural=True, routing=True, authority=True, admitted=False,
                selected=selected, candidates=authorised, denied=denied,
                ambiguous=len(authorised) > 1,
                note=("several declared edges accept this schema; the first by (source, target) is "
                      "selected and the rest are listed") if len(authorised) > 1 else
                     "one declared edge accepts this schema",
                refused=None)


def summary(registry: dict) -> str:
    if not registry["ok"]:
        lines = ["micronaut registry · INVALID"]
        lines += [f"  {problem['code']}: {problem['detail']}" for problem in registry["problems"][:6]]
        return "\n".join(lines)
    lines = [f"micronaut registry · {len(registry['list'])} agent(s) · "
             f"{len(registry['edges'])} declared edge(s) · {len(registry['schemas'])} schema(s)"]
    for entry in registry["list"]:
        lines.append(f"  {entry['uri']:26} {entry['role']:24} {entry['input_schema']} -> "
                     f"{entry['output_schema']}")
    for edge in registry["edges"]:
        lines.append(f"  edge {edge['source']} -> {edge['target']}  ({edge['capability']})")
    lines.append("  (declaration_only · a declared edge is not an admission)")
    return "\n".join(lines)
