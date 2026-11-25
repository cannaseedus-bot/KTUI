"""Pure validation for GML graphs whose edges bind typed Micronaut columns."""
from __future__ import annotations

from gml2 import Block
import gml_columns


SCHEMA = "gml-wiring/1"
CONTRACT = "typed_column_edges"


def many(block: Block, name: str) -> list:
    return [entry.value for entry in block.entries if entry.name == name]


def one(block: Block, name: str, default=None):
    values = many(block, name)
    if len(values) > 1:
        raise ValueError(f"duplicate {name}")
    return values[0] if values else default


def _shape(block: Block) -> list:
    value = one(block, "shape")
    if not isinstance(value, Block):
        return value if isinstance(value, list) else []
    return [entry.value for entry in value.entries if entry.name == "dim"]


def _provenance(block: Block) -> list[str]:
    value = one(block, "provenance")
    if not isinstance(value, Block):
        return value if isinstance(value, list) else []
    return [entry.value for entry in value.entries if entry.name in ("tag", "value")]


def edge_record(edge: Block) -> dict:
    return dict(source_ref=one(edge, "source_ref"), target_ref=one(edge, "target_ref"),
                type=one(edge, "type"), rank=one(edge, "rank"), shape=_shape(edge),
                provenance=_provenance(edge))


def validate(doc: Block, catalog: dict | None = None) -> dict:
    """Validate GML typed-column edges; never invokes an operator or grants admission."""
    catalog = catalog or gml_columns.load_catalog()
    problems: list[dict] = []
    if one(doc, "schema") != SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}"))
    if one(doc, "contract") != CONTRACT:
        problems.append(dict(code="contract", detail=f"expected {CONTRACT}"))
    if one(doc, "authority") != "declaration_only":
        problems.append(dict(code="authority", detail="wiring must be declaration_only"))
    records = []
    seen = set()
    for index, block in enumerate(many(doc, "edge")):
        if not isinstance(block, Block):
            problems.append(dict(code="edge", detail=f"edge #{index} is not a block"))
            continue
        record = edge_record(block)
        pair = (record.get("source_ref"), record.get("target_ref"))
        if pair in seen:
            problems.append(dict(code="duplicate_edge", detail=f"edge #{index}: {pair}"))
        seen.add(pair)
        result = gml_columns.validate_edge(record, catalog)
        records.append(result)
        for problem in result["problems"]:
            problems.append(dict(code=f"edge_{problem['code']}", detail=f"edge #{index}: {problem['detail']}"))
    return dict(schema="gml-wiring-validation/1", graph_id=one(doc, "graph_id"),
                contract=CONTRACT, state="BINDINGS_VALIDATED" if not problems else "REJECTED",
                ok=not problems, edges=records, problems=problems,
                authority="declaration_only", execution=False, mutation=False)


def validate_edge_record(edge: dict, catalog: dict | None = None) -> dict:
    """Validate one runtime-supplied edge record without parsing or dispatching a graph."""
    catalog = catalog or gml_columns.load_catalog()
    result = gml_columns.validate_edge(edge, catalog)
    return dict(schema="gml-wiring-validation/1", contract=CONTRACT,
                state="BINDINGS_VALIDATED" if result["ok"] else "REJECTED",
                ok=result["ok"], edges=[result], problems=result["problems"],
                authority="declaration_only", execution=False, mutation=False)
