"""A URI-addressed store: schemas as contracts, rows as instances, and the two gaps stated as code.

The mapping is the one the review describes, and this repository already had most of the vocabulary - typed URIs,
declared columns, a registry of contracts, handlers as the only way to read. What was missing is the part that makes
it a *store*: instance URIs, a prefix router, and an honest account of joins and integrity.

    urn:db:<namespace>:table:<name>:v1          a schema document URI ($id), validated on write
    urn:db:<namespace>:row:<name>:<id>          a row instance carrying $schema and $id
    <row>#/customer_uri                         a field address (JSON Pointer fragment)
    <row> customer_uri = <another row URI>      a join, resolved by dereferencing

Backends are selected by URI prefix. The first one is a local directory of JSON documents, because that is
inspectable, diffable, and needs no driver; the interface is a dict of backends, so a SQLite or HTTP one can be added
without touching the store.

Two honest limits, both measurable here rather than described:

    scan()   is a linear read of the backend. There is no index. A query that scans is slow by construction.
    delete() refuses while another row references the target - referential integrity is a write-gate check, not a
             database constraint, and `force=True` records the links it broke.

This is the first component that really writes data. It therefore says `mutation: true` when it writes, and it is
deliberately not reachable from the read-only MCP surface.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
PACKAGE = HOST_ROOT / "kuhul-phase-engine-v0.1.0"
for _candidate in (str(PACKAGE / "core"), str(PACKAGE), str(HOST_ROOT)):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

SCHEMA = "kuhul://uri-db/store/v1"
DEFAULT_ROOT = HOST_ROOT / "data" / "uri-db"
ROW = re.compile(r"^urn:db:[a-z0-9_-]+:row:[a-z0-9_.-]+:[A-Za-z0-9_.-]{1,128}$")
TABLE = re.compile(r"^urn:db:[a-z0-9_-]+:table:[a-z0-9_.-]+:v\d+$")


class StoreError(ValueError):
    """A request the store refuses."""


def table_of(row_uri: str) -> str:
    """`urn:db:finance:row:invoices:inv_1` -> `urn:db:finance:table:invoices:v1`."""
    parts = str(row_uri or "").split(":")
    if len(parts) != 6 or parts[3] != "row":
        raise StoreError(f"{row_uri!r} is not a row URI")
    return f"{parts[0]}:{parts[1]}:{parts[2]}:table:{parts[4]}:v1"


def split_pointer(uri: str) -> tuple[str, str]:
    """`<row>#/properties/amount` -> (row, `properties/amount`)."""
    base, _hash, pointer = str(uri or "").partition("#/")
    return base, pointer.replace("/", ".")


class DirectoryBackend:
    """One namespace on the filesystem: one JSON document per row URI."""

    def __init__(self, root: Path, prefix: str):
        self.root = Path(root)
        self.prefix = prefix

    def path_for(self, uri: str) -> Path:
        if not str(uri).startswith(self.prefix):
            raise StoreError(f"{uri!r} does not belong to {self.prefix!r}")
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(uri)[len(self.prefix):])
        return self.root / f"{stem}.json"

    def read(self, uri: str) -> dict | None:
        path = self.path_for(uri)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, uri: str, document: dict) -> Path:
        path = self.path_for(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path

    def remove(self, uri: str) -> bool:
        path = self.path_for(uri)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def rows(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        documents = []
        for path in sorted(self.root.glob("*.json")):
            try:
                documents.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return documents


class Store:
    """A prefix router over backends, with schema-enforced writes and link-checked deletes."""

    def __init__(self, backends: dict[str, object], *, schemas: dict | None = None):
        self.backends = dict(backends)
        self.schemas = dict(schemas or {})

    # -- routing ---------------------------------------------------------------------------------
    def backend_for(self, uri: str):
        base, _pointer = split_pointer(uri)
        for prefix, backend in self.backends.items():
            if base.startswith(prefix):
                return backend
        raise StoreError(f"no backend routes {uri!r}")

    # -- schema-enforced write -------------------------------------------------------------------
    def register_schema(self, table_uri: str, schema: dict) -> dict:
        if not TABLE.fullmatch(str(table_uri or "")):
            raise StoreError(f"{table_uri!r} is not a table URI")
        if not isinstance(schema, dict) or schema.get("$id") != table_uri:
            raise StoreError("the schema document's $id must equal the table URI it registers")
        self.schemas[table_uri] = schema
        return dict(ok=True, table=table_uri, required=schema.get("required") or [])

    def validate_row(self, document: dict) -> list[dict]:
        table = document.get("$schema")
        schema = self.schemas.get(table)
        if schema is None:
            return [dict(code="schema_not_registered",
                         detail=f"{table!r} is not a registered table; writes are refused")]
        problems: list[dict] = []
        if document.get("$id") != self._row_id(document):
            problems.append(dict(code="row_id", detail="$id must be the row's own URI"))
        for name in schema.get("required") or []:
            if name not in document:
                problems.append(dict(code="required", detail=f"{name} is required by {table}"))
        properties = schema.get("properties") or {}
        for name, rule in properties.items():
            if name not in document:
                continue
            expected = (rule or {}).get("type")
            value = document[name]
            allowed = {"string": str, "number": (int, float), "boolean": bool, "object": dict, "array": list}
            if expected in allowed and not isinstance(value, allowed[expected]):
                problems.append(dict(code="type", detail=f"{name} must be {expected}"))
            if expected == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
                minimum = (rule or {}).get("minimum")
                if minimum is not None and value < minimum:
                    problems.append(dict(code="minimum", detail=f"{name} must be >= {minimum}"))
        return problems

    @staticmethod
    def _row_id(document: dict) -> str:
        return str(document.get("$id") or "")

    def put(self, uri: str, document: dict) -> dict:
        if not ROW.fullmatch(str(uri or "")):
            raise StoreError(f"{uri!r} is not a row URI")
        document = dict(document, **{"$id": uri})
        problems = self.validate_row(document)
        if problems:
            return dict(schema=SCHEMA, ok=False, refused="row_invalid", uri=uri, problems=problems,
                        mutation=False, authority="declaration_only")
        backend = self.backend_for(uri)
        path = backend.write(uri, document)
        return dict(schema=SCHEMA, ok=True, refused=None, uri=uri, path=str(path),
                    mutation=True, authority="declaration_only",
                    note="written: this is a store, not a declaration")

    # -- reads -----------------------------------------------------------------------------------
    def get(self, uri: str) -> dict:
        backend = self.backend_for(uri)
        base, pointer = split_pointer(uri)
        document = backend.read(base)
        if document is None:
            return dict(schema=SCHEMA, ok=False, refused="not_found", uri=uri, record=None,
                        mutation=False, authority="declaration_only")
        if not pointer:
            return dict(schema=SCHEMA, ok=True, refused=None, uri=uri, record=document,
                        mutation=False, authority="declaration_only")
        # A fragment may address a row field (`#/amount`) or the schema's property (`#/properties/amount`).
        # Both are accepted; which one was used is reported, so a caller is never guessing.
        segments = [segment for segment in pointer.split(".") if segment]
        style = "row"
        value, missing = self._walk(document, segments)
        if missing and segments and segments[0] == "properties":
            value, missing = self._walk(document, segments[1:])
            style = "schema"
        if missing:
            return dict(schema=SCHEMA, ok=False, refused="pointer_not_found", uri=uri, record=None,
                        mutation=False, authority="declaration_only")
        return dict(schema=SCHEMA, ok=True, refused=None, uri=uri, record=value, pointer=pointer,
                    pointer_style=style, mutation=False, authority="declaration_only")

    @staticmethod
    def _walk(document, segments) -> tuple[object, bool]:
        value = document
        for step in segments:
            if not isinstance(value, dict) or step not in value:
                return None, True
            value = value[step]
        return value, False

    def join(self, uri: str, field: str, *, depth: int = 1) -> dict:
        """Dereference one field that names another row: the zero-config join, with a depth limit."""
        first = self.get(uri)
        if not first["ok"] or not isinstance(first["record"], dict):
            return dict(schema=SCHEMA, ok=False, refused="not_found", hops=[], record=None,
                        mutation=False, authority="declaration_only")
        hops = [dict(uri=uri, field=field)]
        target = first["record"].get(field)
        if not isinstance(target, str) or ":row:" not in target:
            return dict(schema=SCHEMA, ok=False, refused="no_reference", hops=hops, record=None,
                        mutation=False, authority="declaration_only",
                        detail=f"{field} does not name a row URI")
        current = target
        for _ in range(max(1, int(depth))):
            resolved = self.get(current)
            hops.append(dict(uri=current, field=None))
            if not resolved["ok"]:
                return dict(schema=SCHEMA, ok=False, refused=resolved["refused"], hops=hops, record=None,
                            mutation=False, authority="declaration_only")
            current = resolved["record"]
            if isinstance(current, dict) and isinstance(current.get(field), str) and ":row:" in current[field]:
                current = current[field]
                continue
            return dict(schema=SCHEMA, ok=True, refused=None, hops=hops, record=current,
                        mutation=False, authority="declaration_only")
        return dict(schema=SCHEMA, ok=False, refused="depth_exhausted", hops=hops, record=None,
                    mutation=False, authority="declaration_only")

    def scan(self, prefix: str, predicate=None) -> dict:
        """A linear read. There is no index, and that is the point of measuring it."""
        backend = self.backends.get(prefix)
        if backend is None:
            raise StoreError(f"no backend routes {prefix!r}")
        rows = backend.rows()
        kept = [row for row in rows if predicate is None or predicate(row)]
        return dict(schema=SCHEMA, ok=True, refused=None, prefix=prefix, scanned=len(rows),
                    matched=len(kept), records=kept, mutation=False, authority="declaration_only",
                    note="linear scan: no index exists in this store")

    # -- delete with link checking ---------------------------------------------------------------
    def references_to(self, target_uri: str) -> list[dict]:
        links: list[dict] = []
        for prefix, backend in self.backends.items():
            for row in backend.rows():
                for name, value in row.items():
                    if name == "$id":
                        continue        # a row naming itself is not a foreign key
                    if isinstance(value, str) and value == target_uri:
                        links.append(dict(uri=row.get("$id"), field=name, target=target_uri))
        return links

    def delete(self, uri: str, *, force: bool = False) -> dict:
        backend = self.backend_for(uri)
        if backend.read(uri) is None:
            return dict(schema=SCHEMA, ok=False, refused="not_found", uri=uri, mutation=False,
                        authority="declaration_only")
        links = self.references_to(uri)
        if links and not force:
            return dict(schema=SCHEMA, ok=False, refused="referenced", uri=uri, links=links,
                        mutation=False, authority="declaration_only",
                        note="referential integrity is a write-gate check here, not a database constraint")
        removed = backend.remove(uri)
        return dict(schema=SCHEMA, ok=removed, refused=None if removed else "not_found", uri=uri,
                    links=links, mutation=removed, authority="declaration_only",
                    broken_links=links if force and links else [])


def default_store(root: Path | None = None) -> Store:
    """One namespace on disk, with the finance and crm prefixes the review used as examples."""
    root = Path(root or DEFAULT_ROOT)
    return Store({f"urn:db:finance:row:": DirectoryBackend(root / "finance", "urn:db:finance:row:"),
                  f"urn:db:crm:row:": DirectoryBackend(root / "crm", "urn:db:crm:row:")})


def summary(result: dict) -> str:
    if result.get("ok"):
        return (f"uri-db · ok · {result.get('uri') or result.get('prefix')} · "
                f"mutation {result.get('mutation')}")
    return f"uri-db · {result.get('refused')} · {result.get('uri') or ''}".strip()
