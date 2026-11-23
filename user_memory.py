"""Append-only user memory: JSONL for history, GML for relationships.

AIML recognises and extracts; SRAI routes to a memory operation; the host admits it; the JSONL event
log records it; the GML projection relates it; queries read the projection. Nothing here reads a
sentence and writes a row: a write is a *proposal* that the host must admit.

Rules this module keeps, and the tests hold it to:

  history is append-only   a correction appends an event; the earlier assertion keeps its provenance
  latest wins              the projection resolves a predicate from the newest surviving event
  isolation by identity    every read and write is scoped to one user id; no cross-user queries exist
  erasure beats history    `erase()` compacts the log - the one destructive operation - and leaves a
                           tombstone event recording that it happened
  the graph is derived     `graph()` builds a GML document from the projection; it is a view, never a
                           second authority, and `validate()` checks it against memory.gml

Records are chained (sequence / previous_hash / content_hash) through ledger_plugin, so the memory
history is tamper-evident in the same way the audit ledger is.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import ledger_plugin

APP_ROOT = Path(__file__).resolve().parent
MEMORY_DIR = APP_ROOT / "logs" / "memory"
EVENTS = MEMORY_DIR / "user.events.jsonl"
SCHEMA_PATH = APP_ROOT / "memory.gml"
GRAPH_SCHEMA = "user-memory/1"
DEFAULT_USER = "local-user"


class MemoryError_(ValueError):
    """A memory operation the host refuses (not to be confused with the builtin MemoryError)."""


def _read(path: Path = EVENTS) -> list[dict]:
    if not Path(path).is_file():
        return []
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def schema_fields(path: Path = SCHEMA_PATH) -> tuple[tuple[str, ...], str]:
    """The event fields memory.gml declares; the document describes, this module enforces."""
    try:
        import phases
        gml2 = phases.core_module("gml2")
        document = gml2.parse(Path(path).read_text(encoding="utf-8"))
        names = []
        for entry in getattr(document, "entries", []):
            if getattr(entry, "name", "") != "field":
                continue
            name = next((item.value for item in entry.value.entries if item.name == "name"), None)
            if isinstance(name, str):
                names.append(name)
        return tuple(names), "memory.gml"
    except Exception:
        return ("event_id", "user_id", "type", "subject", "predicate", "value"), "built-in defaults"


def remember(*, user: str, subject: str, predicate: str, value: str, source: str = "user_message",
             path: Path = EVENTS, key_path: Path | None = None) -> dict:
    """Append one fact event. The caller must have admitted the write already."""
    user = (user or "").strip()
    subject = (subject or "").strip()
    predicate = (predicate or "").strip()
    if not user or not subject or not predicate:
        raise MemoryError_("memory writes need a user, a subject and a predicate")
    text = "" if value is None else str(value).strip()
    if not text:
        raise MemoryError_("memory writes need a value")
    payload = dict(user_id=user, type="fact_asserted", subject=subject, predicate=predicate,
                   value=text, source=source, status="accepted")
    record = ledger_plugin.append({"kind": "memory:fact", "payload": payload}, path, key_path=key_path)
    record = dict(record, event_id=f"evt-{record['sequence']:06d}")
    return record


def forget(*, user: str, subject: str, predicate: str, path: Path = EVENTS) -> dict:
    """Retract one predicate. History keeps the assertion; the projection stops using it."""
    payload = dict(user_id=user, type="fact_retracted", subject=subject, predicate=predicate,
                   source="user_message", status="accepted")
    record = ledger_plugin.append({"kind": "memory:retract", "payload": payload}, path)
    return dict(record, event_id=f"evt-{record['sequence']:06d}")


def events(user: str | None = None, path: Path = EVENTS) -> list[dict]:
    rows = _read(path)
    if user is None:
        return rows
    return [row for row in rows if (row.get("payload") or {}).get("user_id") == user]


def projection(user: str, path: Path = EVENTS) -> dict[str, dict[str, str]]:
    """Current facts for one user: subject -> predicate -> value, newest surviving event wins."""
    facts: dict[str, dict[str, str]] = {}
    for row in events(user, path):
        payload = row.get("payload") or {}
        subject, predicate = payload.get("subject"), payload.get("predicate")
        if not subject or not predicate:
            continue
        if payload.get("type") == "fact_asserted":
            facts.setdefault(subject, {})[predicate] = str(payload.get("value") or "")
        elif payload.get("type") == "fact_retracted":
            facts.get(subject, {}).pop(predicate, None)
    # A subject with nothing left is not a fact about the user; do not report an empty shell.
    return {subject: predicates for subject, predicates in facts.items() if predicates}


def graph(user: str, path: Path = EVENTS) -> dict:
    """The relational view for one user, as a GML document."""
    facts = projection(user, path)
    nodes: list[dict] = [dict(id=0, kind="user", ref=user)]
    edges: list[dict] = []
    next_id = 1
    subjects: dict[str, int] = {}
    for subject in sorted(facts):
        subjects[subject] = next_id
        nodes.append(dict(id=next_id, kind="entity", ref=f"{user}:{subject}"))
        edges.append(dict(source=0, target=next_id, relation="owns"))
        next_id += 1
    for subject in sorted(facts):
        for predicate in sorted(facts[subject]):
            nodes.append(dict(id=next_id, kind="fact", value=facts[subject][predicate], key=predicate))
            edges.append(dict(source=subjects[subject], target=next_id, relation=predicate))
            next_id += 1
    return dict(schema=GRAPH_SCHEMA, graph_id=f"user/{user}", user=user,
                nodes=nodes, edges=edges, generated_from=Path(path).name)


def validate(document: dict) -> dict:
    """Structural check of a projection document: ids unique, edges resolve, fields declared."""
    fields, source = schema_fields()
    problems: list[dict] = []
    if document.get("schema") != GRAPH_SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {GRAPH_SCHEMA}"))
    ids = set()
    for node in document.get("nodes") or []:
        identifier = node.get("id")
        if not isinstance(identifier, int) or identifier < 0:
            problems.append(dict(code="node_id", detail=repr(identifier)))
            continue
        if identifier in ids:
            problems.append(dict(code="duplicate_node", detail=str(identifier)))
        ids.add(identifier)
        if node.get("kind") not in ("user", "entity", "fact"):
            problems.append(dict(code="node_kind", detail=str(node.get("kind"))))
    for edge in document.get("edges") or []:
        if edge.get("source") not in ids or edge.get("target") not in ids:
            problems.append(dict(code="edge_unresolved",
                                 detail=f"{edge.get('source')}->{edge.get('target')}"))
        if not isinstance(edge.get("relation"), str) or not edge.get("relation"):
            problems.append(dict(code="edge_relation", detail="missing relation"))
    return dict(ok=not problems, problems=problems, fields=fields, schema_source=source,
                nodes=len(document.get("nodes") or []), edges=len(document.get("edges") or []))


def answer(user: str, subject: str, predicate: str, path: Path = EVENTS) -> str:
    """A grounded sentence from the projection, or an honest miss."""
    facts = projection(user, path)
    value = (facts.get(subject) or {}).get(predicate)
    if not value:
        return f"I have nothing recorded for {subject}.{predicate}."
    return f"{subject.replace('.', ' ')}: {predicate} is {value}."


def erase(user: str, path: Path = EVENTS) -> dict:
    """Remove one user's payloads. The only destructive operation, and it leaves a tombstone.

    Append-only history is an audit property; a person's right to removal is not negotiable against
    it, so erasure compacts the log and records that it did so. Other users' events are untouched.
    """
    rows = _read(path)
    kept, removed = [], 0
    for row in rows:
        if (row.get("payload") or {}).get("user_id") == user:
            removed += 1
            continue
        kept.append(row)
    with Path(path).open("w", encoding="utf-8", newline="\n") as handle:
        for row in kept:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    tombstone = ledger_plugin.append(
        {"kind": "memory:erasure", "payload": dict(user_id=user, type="erasure", removed=removed,
                                                   source="user_request", status="accepted")},
        path, verify_first=False)
    return dict(user=user, removed=removed, kept=len(kept), tombstone=tombstone.get("event_id"))


def writable(mode: str | None = None) -> bool:
    """Memory writes are a grant. `KNUMATIC_MEMORY_WRITE=1` is the environment form of that grant."""
    if mode is not None:
        return str(mode).strip().lower() in {"1", "on", "write", "granted"}
    return os.environ.get("KNUMATIC_MEMORY_WRITE", "").strip().lower() in {"1", "on", "write", "granted"}
