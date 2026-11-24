"""The shared corpus resolver: one knowledge graph, six specialised views of it.

The architecture's claim is that every micronaut reads the same corpus through a different lens, and that
*reading* is not *learning*. This module implements both halves and keeps them apart:

    corpus://shared/v1  ->  authorized retrieval  ->  typed evidence  ->  micronaut-specific projection

Three operations, deliberately distinct:

    retrieval          reads existing knowledge; no weights change, nothing is written
    incremental update a *proposal*; persisted only after XCFE admission, and recorded as such
    model training     a separate process; a corpus update never retrains a model

A source may be declared and unavailable (`gramstore://ngrams` here). The declaration says so, and the
resolver refuses it with a reason instead of pretending the failure is the caller's fault.

Every result carries `execution: false`, `mutation: false`, `persistence: false`: retrieval is a read,
a proposal is a proposal, and neither is an admission.
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

import aiml_graph  # noqa: E402
import user_memory  # noqa: E402

MANIFEST = PACKAGE / "data" / "corpus.json"
SCHEMA = "kuhul-corpus-access/v1"
OPERATORS = ("filter", "map", "fold", "accumulate", "reduce")
SCOPES = ("shared", "self")
ACCESS = ("scope_checked", "open")

_BANKS = ("identity.aiml", "smalltalk.aiml", "memory.aiml", "gitops.aiml", "_override.aiml")


def load(path: Path = MANIFEST) -> dict:
    """Parse and validate the corpus declaration: sources, scopes, access policy, boundaries."""
    path = Path(path)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, problems=[dict(code="unreadable", detail=str(error))], sources={})
    problems: list[dict] = []
    if record.get("schema") != SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}"))
    if record.get("authority") != "declaration_only":
        problems.append(dict(code="authority", detail="a corpus declaration is declaration_only"))
    sources: dict[str, dict] = {}
    for index, source in enumerate(record.get("sources") or []):
        uri = str(source.get("uri") or "")
        if not uri or "://" not in uri:
            problems.append(dict(code="source_uri", detail=f"#{index} {uri!r}"))
            continue
        if uri in sources:
            problems.append(dict(code="duplicate_source", detail=uri))
            continue
        if source.get("scope") not in SCOPES:
            problems.append(dict(code="scope", detail=f"{uri}: {source.get('scope')!r}"))
        if not str(source.get("capability") or "").strip():
            problems.append(dict(code="capability", detail=f"{uri}: no capability declared"))
        sources[uri] = dict(uri=uri, kind=source.get("kind"), available=bool(source.get("available")),
                            capability=str(source.get("capability") or ""),
                            scope=source.get("scope") or "shared",
                            note=source.get("note") or "")
    operators = [str(name) for name in record.get("operators") or []]
    unknown = [name for name in operators if name not in OPERATORS]
    if unknown:
        problems.append(dict(code="operators", detail=str(unknown)))
    access = record.get("access") or {}
    if access.get("read") not in ACCESS:
        problems.append(dict(code="read_access", detail=f"{access.get('read')!r}"))
    if access.get("write") != "xcfe_admitted":
        problems.append(dict(code="write_access",
                             detail="write must be xcfe_admitted, never implied by the declaration"))
    boundaries = record.get("boundaries") or {}
    for key in ("retrieval", "incremental_learning", "model_training"):
        if not str(boundaries.get(key) or "").strip():
            problems.append(dict(code="boundary", detail=f"{key} must be declared"))
    training_text = str(boundaries.get("model_training") or "").lower()
    if "separate" not in training_text or "train" not in training_text:
        problems.append(dict(code="boundary",
                             detail="model_training must state that it is a separate process"))
    return dict(ok=not problems, problems=problems, uri=record.get("uri"), sources=sources,
                operators=operators, access=access, boundaries=boundaries,
                authority=record.get("authority"))


# -- retrieval ---------------------------------------------------------------------------------------
def _categories(limit: int) -> list[dict]:
    found = []
    for bank in _BANKS:
        path = HOST_ROOT / bank
        if not path.is_file():
            continue
        for category in aiml_graph.read_categories(path):
            if category.unsupported:
                continue
            found.append(dict(kind="pattern", ref=f"aiml://category/{category.category_id}",
                              value=category.pattern, source="aiml://categories",
                              redirect=category.srai or None))
            if len(found) >= limit:
                return found
    return found


def _relations(user: str, limit: int) -> list[dict]:
    events = user_memory.events(user)
    latest: dict[tuple[str, str], dict] = {}
    for index, event in enumerate(events):
        payload = event.get("payload") or {}
        if payload.get("type") != "fact_asserted":
            continue
        key = (payload.get("subject") or "", payload.get("predicate") or "")
        latest[key] = dict(kind="relation", value=str(payload.get("value") or ""),
                           ref=f"gml://relations/{user}#{key[0]}.{key[1]}",
                           source="gml://relations", subject=key[0], predicate=key[1],
                           event_id=event.get("event_id"), event_index=index)
    rows = [latest[key] for key in sorted(latest)]
    return rows[-limit:]


def _events(user: str, limit: int) -> list[dict]:
    rows = user_memory.events(user)[-limit:]
    return [dict(kind="event", ref=f"memory://jsonl/{user}#{event.get('event_id')}",
                 value=(event.get("payload") or {}).get("type"),
                 source="memory://jsonl", event_id=event.get("event_id"),
                 sequence=event.get("sequence")) for event in rows]


def _vectors(limit: int) -> list[dict]:
    folder = HOST_ROOT / "aiml-embeddinggemma2-vectors"
    manifest = folder / "manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError("no embedding manifest")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    return [dict(kind="vectors", ref="vectors://embeddinggemma2",
                 value=dict(model=document.get("model"), rows=document.get("categories"),
                            dimensions=document.get("dimensions"), dtype=document.get("dtype")),
                 source="vectors://embeddinggemma2")]


READERS = {"aiml://categories": lambda caller, limit: _categories(limit),
           "gml://relations": lambda caller, limit: _relations(caller, limit),
           "memory://jsonl": lambda caller, limit: _events(caller, limit),
           "vectors://embeddinggemma2": lambda caller, limit: _vectors(limit)}


def retrieve(manifest: dict, source_uri: str, *, caller: str = "", granted: set | None = None,
             limit: int = 20) -> dict:
    """Read one source under the declared access policy. Evidence in, nothing written out."""
    granted = set(granted or ())
    envelope = dict(schema=SCHEMA, corpus=manifest.get("uri"), source=str(source_uri),
                    authority="declaration_only", execution=False, mutation=False,
                    persistence=False)
    source = (manifest.get("sources") or {}).get(str(source_uri))
    if source is None:
        return dict(envelope, ok=False, refused="source_not_declared", evidence=[],
                    reason=f"{source_uri!r} is not in the corpus declaration")
    if not source["available"]:
        return dict(envelope, ok=False, refused="source_unavailable", evidence=[],
                    reason=source["note"] or "the declaration marks this source unavailable")
    if source["capability"] not in granted:
        return dict(envelope, ok=False, refused="capability_not_granted", evidence=[],
                    reason=f"the caller does not hold {source['capability']}")
    if source["scope"] == "self":
        if not caller:
            return dict(envelope, ok=False, refused="scope_required", evidence=[],
                        reason="this source is scoped to an identity, and none was supplied")
        owner = str(caller)
    else:
        owner = str(caller or "")
    reader = READERS.get(source["uri"])
    if reader is None:
        return dict(envelope, ok=False, refused="no_reader", evidence=[],
                    reason=f"no reader is bound for {source['uri']}")
    try:
        evidence = reader(owner, max(1, int(limit)))
    except FileNotFoundError as error:
        return dict(envelope, ok=False, refused="source_unavailable", evidence=[],
                    reason=str(error))
    return dict(envelope, ok=True, refused=None, scope=source["scope"], kind=source["kind"],
                evidence=evidence, count=len(evidence))


def retrieve_all(manifest: dict, *, caller: str = "", granted: set | None = None,
                 limit: int = 20) -> dict:
    """Every readable source, with the refusals kept alongside - the whole view for one caller."""
    results = {uri: retrieve(manifest, uri, caller=caller, granted=granted, limit=limit)
               for uri in sorted(manifest.get("sources") or {})}
    readable = {uri: result for uri, result in results.items() if result["ok"]}
    refused = {uri: result["refused"] for uri, result in results.items() if not result["ok"]}
    return dict(schema=SCHEMA, corpus=manifest.get("uri"), caller=caller,
                readable=sorted(readable), refused=refused, results=results,
                authority="declaration_only", execution=False, mutation=False, persistence=False)


# -- the learning boundary -----------------------------------------------------------------------------
def propose_update(manifest: dict, *, source: str, proposition: dict, caller: str = "") -> dict:
    """An incremental-learn proposal. It is not a write, and it says what would be required."""
    source_record = (manifest.get("sources") or {}).get(str(source))
    if source_record is None:
        return dict(schema="kuhul-corpus-update/1", ok=False, refused="source_not_declared",
                    persisted=False, execution=False, persistence=False)
    return dict(schema="kuhul-corpus-update/1", ok=True, corpus=manifest.get("uri"),
                source=str(source), caller=caller, proposition=dict(proposition or {}),
                requires=manifest.get("access", {}).get("write", "xcfe_admitted"),
                persisted=False, admitted=False, execution=False, mutation=False,
                persistence=False,
                note="a proposal: persistence needs XCFE admission, and a corpus update never "
                     "retrains a model")


def view(manifest: dict, *, caller: str = "", granted: set | None = None) -> dict:
    """What one caller may read - the micronaut-specific projection of the shared corpus."""
    granted = set(granted or ())
    readable, refused = [], []
    for uri, source in sorted((manifest.get("sources") or {}).items()):
        if not source["available"]:
            refused.append(dict(uri=uri, refused="source_unavailable"))
        elif source["capability"] not in granted:
            refused.append(dict(uri=uri, refused="capability_not_granted",
                                needs=source["capability"]))
        elif source["scope"] == "self" and not caller:
            refused.append(dict(uri=uri, refused="scope_required"))
        else:
            readable.append(dict(uri=uri, kind=source["kind"], scope=source["scope"]))
    return dict(schema=SCHEMA, corpus=manifest.get("uri"), caller=caller,
                readable=readable, refused=refused,
                authority="declaration_only", execution=False)


def summary(manifest: dict) -> str:
    if not manifest["ok"]:
        lines = ["corpus · INVALID"]
        lines += [f"  {problem['code']}: {problem['detail']}" for problem in manifest["problems"]]
        return "\n".join(lines)
    lines = [f"corpus {manifest['uri']} · {len(manifest['sources'])} source(s) · "
             f"{len(manifest['operators'])} operator(s) · {manifest['authority']}"]
    for uri, source in sorted(manifest["sources"].items()):
        state = "available" if source["available"] else "UNAVAILABLE"
        lines.append(f"  {uri:28} {source['kind']:11} {source['scope']:7} {state}")
    lines.append(f"  read: {manifest['access'].get('read')} · "
                 f"write: {manifest['access'].get('write')}")
    lines.append(f"  training: {manifest['boundaries'].get('model_training')}")
    return "\n".join(lines)
