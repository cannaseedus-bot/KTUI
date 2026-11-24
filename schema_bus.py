"""The schema URI message bus: typed handoffs between micronauts, where a valid message is not a permission.

Routing a message needs four things, and each failure has its own name so it cannot hide behind another:

    schema      the URI is registered and its version matches the message
    payload     every required field is present
    edge        a declared producer -> consumer edge exists for that schema
    capability  the producer's capability is granted to this caller

That is `SchemaCompatible and EdgeDeclared and CapabilityAuthorized`; admission stays with XCFE, so every
result reports `admitted: false`.

Version evolution is explicit: a v1 payload is only turned into v2 by a **registered adapter**. There is no
silent coercion, because adding a field the consumer requires is a change in meaning.
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

SCHEMA = "kuhul://schemas/v1"
REGISTRY = PACKAGE / "data" / "schemas.json"
AUTHORITY_CLASSES = ("proposal", "verified", "evidence", "diagnostic")


def load(path: Path | None = None) -> dict:
    """Load the schema registry, the declared edges and the version adapters."""
    path = Path(path or REGISTRY)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, problems=[dict(code="unreadable", detail=str(error))],
                    schemas={}, edges=[], adapters={})
    problems: list[dict] = []
    if record.get("schema") != SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}"))
    if record.get("authority") != "declaration_only":
        problems.append(dict(code="authority", detail="a schema registry is declaration_only"))
    schemas = {}
    for uri, entry in (record.get("schemas") or {}).items():
        if not str(uri).startswith("urn:kuhul:schema:"):
            problems.append(dict(code="uri", detail=f"{uri!r} is not a schema urn"))
        if entry.get("authority") not in AUTHORITY_CLASSES:
            problems.append(dict(code="class", detail=f"{uri}: {entry.get('authority')!r}"))
        if not entry.get("required"):
            problems.append(dict(code="required", detail=f"{uri}: no required fields"))
        schemas[str(uri)] = dict(entry, uri=str(uri))
    edges = []
    for index, edge in enumerate(record.get("edges") or []):
        if edge.get("schema") not in schemas:
            problems.append(dict(code="edge", detail=f"#{index}: unknown schema {edge.get('schema')!r}"))
            continue
        edges.append(dict(edge))
    adapters = {}
    for adapter in record.get("adapters") or []:
        accepts, emits = adapter.get("accepts"), adapter.get("emits")
        if accepts not in schemas or emits not in schemas:
            problems.append(dict(code="adapter", detail=f"{adapter.get('id')}: unknown endpoint"))
            continue
        adapters[(accepts, emits)] = dict(adapter)
    return dict(ok=not problems, problems=problems, schemas=schemas, edges=edges,
                adapters=adapters, authority="declaration_only")


# -- validation ---------------------------------------------------------------------------------------
def validate(registry: dict, message: dict) -> dict:
    """Check one message against its declared schema. No routing, no admission."""
    uri = str((message or {}).get("schema_uri") or "")
    problems: list[dict] = []
    entry = (registry.get("schemas") or {}).get(uri)
    if entry is None:
        return dict(ok=False, schema_uri=uri, problems=[dict(code="unknown_schema",
                                                            detail=f"{uri!r} is not registered")])
    payload = message.get("payload")
    if not isinstance(payload, dict):
        problems.append(dict(code="payload", detail="payload must be an object"))
        payload = {}
    for field in entry.get("required") or []:
        if field not in payload:
            problems.append(dict(code="payload_missing_field", detail=f"{uri}: {field!r}"))
    declared = entry.get("authority")
    claimed = str(message.get("authority") or "").strip().lower()
    if claimed != declared:
        problems.append(dict(code="authority_mismatch",
                             detail=f"{uri} is {declared}, message claims {claimed or '(none)'!r}"))
    version = message.get("version")
    if version is not None and int(version) != int(entry.get("version")):
        problems.append(dict(code="version_mismatch",
                             detail=f"{uri} is version {entry.get('version')}, message says {version}"))
    return dict(ok=not problems, schema_uri=uri, problems=problems, entry=entry,
                producer=message.get("producer"), authority_class=declared)


# -- routing ------------------------------------------------------------------------------------------
def route(registry: dict, message: dict, *, consumer: str, granted: set | None = None) -> dict:
    """Deliver only when schema, edge and capability all hold. Admission is never granted here."""
    granted = set(granted or ())
    checked = validate(registry, message)
    refused = None
    reasons = list(checked["problems"])
    edges = []
    if not checked["ok"]:
        refused = reasons[0]["code"] if reasons else "invalid_message"
    else:
        uri = checked["schema_uri"]
        producer = str(message.get("producer") or "")
        edges = [edge for edge in registry["edges"]
                 if edge["schema"] == uri and edge["from"] == producer and edge["to"] == consumer]
        if not edges:
            refused = "no_declared_edge"
            reasons.append(dict(code="no_declared_edge",
                                detail=f"no edge {producer or '(no producer)'} -> {consumer} for {uri}"))
        else:
            capable = [edge for edge in edges if edge.get("capability") in granted]
            if not capable:
                refused = "capability_not_granted"
                reasons.append(dict(code="capability_not_granted",
                                    detail=f"{producer} needs {edges[0].get('capability')}"))
    return dict(schema="kuhul://bus/route/v1", delivered=refused is None, refused=refused,
                consumer=consumer, schema_uri=checked.get("schema_uri"),
                producer=message.get("producer"), edges=edges, problems=reasons,
                admitted=False, authority="declaration_only", execution=False,
                note="a delivered message is not an admitted operation")


def consumers(registry: dict, schema_uri: str) -> list[dict]:
    return [edge for edge in registry["edges"] if edge["schema"] == schema_uri]


# -- version adapters ----------------------------------------------------------------------------------
def adapt(registry: dict, message: dict, *, target: str) -> dict:
    """Convert a message through a registered adapter. Never coerces silently."""
    source = str(message.get("schema_uri") or "")
    adapter = (registry.get("adapters") or {}).get((source, target))
    if adapter is None:
        return dict(ok=False, refused="no_registered_adapter", source=source, target=target,
                    reason=f"no adapter declares {source} -> {target}")
    entry = registry["schemas"][target]
    payload = dict(message.get("payload") or {})
    for field in adapter.get("adds") or []:
        if field in payload:
            continue
        # The adapter may only *declare* the gap it fills; it cannot invent the value.
        return dict(ok=False, refused="missing_source_evidence", source=source, target=target,
                    reason=f"{target} requires {field!r}, which the adapter cannot supply on its own")
    return dict(ok=True, schema_uri=target, version=entry["version"],
                payload=payload, authority=entry["authority"], producer=message.get("producer"),
                adapter=adapter.get("id"), admitted=False, execution=False)


# -- the learning pipeline ----------------------------------------------------------------------------
def learning_delta(candidate: dict, *, operation: str = "assert_relation") -> dict:
    """A proposal to change the graph. It is not a write, and it says what would be required."""
    return dict(schema_uri="urn:kuhul:schema:learning-delta:v1",
                producer="micronaut://v1/learning",
                payload=dict(operation=operation,
                             target=f"{candidate.get('source')}->{candidate.get('target')}",
                             evidence=dict(relation=candidate.get("relation"),
                                           score=candidate.get("score"))),
                authority="proposal", requires="xcfe_admission", persisted=False,
                admitted=False, execution=False)


def verified_delta(delta: dict, *, verdict: str, evidence: str = "") -> dict:
    """A verified candidate: only a PASS or FAIL verdict produces one."""
    if str(verdict or "").upper() not in ("PASS", "FAIL"):
        raise ValueError(f"a delta is verified only on PASS or FAIL, not {verdict!r}")
    return dict(schema_uri="urn:kuhul:schema:verified-delta:v1",
                producer="micronaut://v1/ch_en",
                payload=dict(delta=dict(delta.get("payload") or {}), verdict=str(verdict).upper(),
                             evidence=evidence),
                authority="verified", admitted=False, execution=False)


def summary(registry: dict) -> str:
    if not registry["ok"]:
        lines = ["schema bus · INVALID"]
        lines += [f"  {problem['code']}: {problem['detail']}" for problem in registry["problems"]]
        return "\n".join(lines)
    lines = [f"schema bus · {len(registry['schemas'])} schema(s) · {len(registry['edges'])} edge(s) · "
             f"{len(registry['adapters'])} adapter(s)"]
    for uri, entry in sorted(registry["schemas"].items()):
        lines.append(f"  {uri:46} v{entry['version']} · {entry['authority']}")
    return "\n".join(lines)
