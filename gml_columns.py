"""Declaration-only URI and typed-column contracts for GML Micronauts.

This module resolves addresses and validates edge metadata.  It deliberately does not
dispatch operators, run a recursion engine, grant capabilities, or perform XCFE admission.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit


HOST_ROOT = Path(__file__).resolve().parent
CATALOG_PATH = HOST_ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "gml-operator-columns.json"
SCHEMA = "kuhul://gml/operators/v1"
ROOT_URI = "micronaut://gml/relations"
REQUIRED_OPERATORS = ("unfold", "map", "filter", "fold", "accumulate", "reduce", "hylo")
ADDRESS_SPACES = ("micronaut", "gml", "model")
_TYPE_VAR = re.compile(r"^[A-Z]$")


class ColumnContractError(ValueError):
    """A URI, operator catalog, or typed edge contradicts the declaration contract."""


def _entries(block: dict, key: str) -> list:
    value = block.get(key)
    return value if isinstance(value, list) else []


def _type_parts(value: str) -> tuple[str, tuple[str, ...]]:
    text = str(value or "").strip()
    if not text:
        raise ColumnContractError("type must be a non-empty string")
    if "<" not in text:
        return text, ()
    if not text.endswith(">"):
        raise ColumnContractError(f"malformed generic type {text!r}")
    base, inner = text.split("<", 1)
    inner = inner[:-1]
    parts, depth, start = [], 0, 0
    for index, char in enumerate(inner):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(inner[start:index].strip())
            start = index + 1
    parts.append(inner[start:].strip())
    if not base or any(not item for item in parts):
        raise ColumnContractError(f"malformed generic type {text!r}")
    return base.strip(), tuple(parts)


def _type_accepts(declared: str, actual: str) -> bool:
    """Return whether a declared port accepts one concrete edge type."""
    declared_base, declared_args = _type_parts(declared)
    actual_base, actual_args = _type_parts(actual)
    if _TYPE_VAR.fullmatch(declared_base):
        return len(declared_args) == len(actual_args)
    if declared_base != actual_base or len(declared_args) != len(actual_args):
        return False
    return all(_type_accepts(left, right) if not _TYPE_VAR.fullmatch(left) else True
               for left, right in zip(declared_args, actual_args))


def _shape_matches(declared: list, actual: list) -> bool:
    if len(declared) != len(actual):
        return False
    for left, right in zip(declared, actual):
        if left in ("*", "?") or right in ("*", "?"):
            continue
        if type(left) is int or type(right) is int:
            if left != right:
                return False
        elif str(left) != str(right):
            return False
    return True


def _valid_port(name: str, port: dict, *, operator: str) -> list[dict]:
    problems: list[dict] = []
    if not isinstance(port, dict):
        return [dict(code="column_shape", detail=f"{operator}/{name} is not an object")]
    if port.get("direction") not in ("input", "output"):
        problems.append(dict(code="column_direction", detail=f"{operator}/{name}"))
    if not isinstance(port.get("type"), str) or not port["type"].strip():
        problems.append(dict(code="column_type", detail=f"{operator}/{name}"))
    else:
        try:
            _type_parts(port["type"])
        except ColumnContractError as error:
            problems.append(dict(code="column_type", detail=str(error)))
    rank = port.get("rank")
    shape = port.get("shape")
    if type(rank) is not int or rank < 0:
        problems.append(dict(code="column_rank", detail=f"{operator}/{name}"))
    if not isinstance(shape, list) or len(shape) != rank:
        problems.append(dict(code="column_shape", detail=f"{operator}/{name}: rank/shape mismatch"))
    if not isinstance(port.get("provenance"), list) or not all(
            isinstance(item, str) and item.strip() for item in port.get("provenance", [])):
        problems.append(dict(code="column_provenance", detail=f"{operator}/{name}"))
    return problems


def validate_catalog(record: dict) -> list[dict]:
    problems: list[dict] = []
    if record.get("schema") != SCHEMA:
        problems.append(dict(code="schema", detail=f"expected {SCHEMA}"))
    if record.get("authority") != "declaration_only":
        problems.append(dict(code="authority", detail="catalog must be declaration_only"))
    spaces = record.get("address_spaces") or {}
    for space in ADDRESS_SPACES:
        if space not in spaces:
            problems.append(dict(code="address_space", detail=f"missing {space}"))
    micronauts = record.get("micronauts") or {}
    root = micronauts.get(ROOT_URI)
    if not isinstance(root, dict):
        problems.append(dict(code="micronaut", detail=f"missing {ROOT_URI}"))
    elif root.get("authority") != "declaration_only":
        problems.append(dict(code="authority", detail=f"{ROOT_URI} must be declaration_only"))
    operators = record.get("operators") or {}
    missing = [name for name in REQUIRED_OPERATORS if name not in operators]
    if missing:
        problems.append(dict(code="operators", detail=f"missing {missing}"))
    for name, operator in operators.items():
        uri = operator.get("uri") if isinstance(operator, dict) else None
        expected = f"{ROOT_URI}/operators/{name}"
        if uri != expected:
            problems.append(dict(code="operator_uri", detail=f"{name}: expected {expected!r}"))
        columns = operator.get("columns") if isinstance(operator, dict) else None
        if not isinstance(columns, dict) or not columns:
            problems.append(dict(code="columns", detail=f"{name} declares no columns"))
            continue
        for column, port in columns.items():
            problems.extend(_valid_port(column, port, operator=name))
    if isinstance(root, dict):
        declared = root.get("operators") or []
        if sorted(declared) != sorted(REQUIRED_OPERATORS):
            problems.append(dict(code="micronaut_operators",
                                 detail=f"{ROOT_URI} must declare {list(REQUIRED_OPERATORS)}"))
    hylo = operators.get("hylo") or {}
    recursion = hylo.get("recursion") if isinstance(hylo, dict) else None
    if not isinstance(recursion, dict):
        problems.append(dict(code="hylo_recursion", detail="HYLO recursion contract is missing"))
    else:
        if recursion.get("unfold_operator") != "unfold" or recursion.get("fold_operator") != "fold":
            problems.append(dict(code="hylo_recursion", detail="HYLO must bind UNFOLD and FOLD"))
        if recursion.get("cycle_policy") != "visited_set":
            problems.append(dict(code="hylo_cycle", detail="HYLO requires visited_set cycle handling"))
        if type(recursion.get("max_depth")) is not int or recursion["max_depth"] < 1:
            problems.append(dict(code="hylo_termination", detail="HYLO max_depth must be positive"))
        if recursion.get("materialization") not in ("optional", "required"):
            problems.append(dict(code="hylo_materialization", detail="HYLO materialization policy missing"))
    return problems


def load_catalog(path: Path | None = None) -> dict:
    path = Path(path or CATALOG_PATH)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ColumnContractError(f"cannot load operator catalog {path}: {error}") from error
    problems = validate_catalog(record)
    if problems:
        raise ColumnContractError("; ".join(f"{p['code']}: {p['detail']}" for p in problems))
    return record


def _address_metadata(uri: str, *, kind: str, **extra) -> dict:
    return dict(schema=SCHEMA, uri=uri, kind=kind, address_space="micronaut",
                authority="declaration_only", execution=False, mutation=False, **extra)


def resolve_column(uri: str, catalog: dict | None = None) -> dict:
    """Resolve a typed Micronaut column without granting or dispatching anything."""
    catalog = catalog or load_catalog()
    text = str(uri or "").strip()
    parsed = urlsplit(text)
    if parsed.scheme != "micronaut" or parsed.netloc != "gml" or parsed.query or parsed.fragment:
        raise ColumnContractError(f"not a GML Micronaut address: {uri!r}")
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parts == ["relations"]:
        return _address_metadata(text, kind="micronaut", role="graph_computation",
                                 graph_uri="gml://relations", operators=list(REQUIRED_OPERATORS))
    if len(parts) == 3 and parts[:2] == ["relations", "operators"]:
        name = parts[2]
        operator = (catalog.get("operators") or {}).get(name)
        if operator is None:
            raise ColumnContractError(f"unknown GML operator: {name!r}")
        return _address_metadata(text, kind="operator", operator=name,
                                 operator_uri=operator["uri"], columns=sorted(operator["columns"]))
    if len(parts) == 5 and parts[:2] == ["relations", "operators"] and parts[3] == "columns":
        name, column = parts[2], parts[4]
        operator = (catalog.get("operators") or {}).get(name)
        if operator is None or column not in operator.get("columns", {}):
            raise ColumnContractError(f"unknown GML operator column: {name}/{column}")
        return _address_metadata(text, kind="column", micronaut_uri=ROOT_URI,
                                 operator=name, operator_uri=operator["uri"], column=column,
                                 **dict(operator["columns"][column]))
    raise ColumnContractError(f"invalid GML Micronaut address: {uri!r}")


def resolve_address(uri: str, catalog: dict | None = None) -> dict:
    """Resolve one of the three declared address spaces; only micronaut columns are typed ports."""
    text = str(uri or "").strip()
    parsed = urlsplit(text)
    if parsed.scheme == "micronaut":
        return resolve_column(text, catalog=catalog)
    if parsed.scheme == "gml" and parsed.netloc and not parsed.query and not parsed.fragment:
        return dict(schema=SCHEMA, uri=text, kind="graph", address_space="gml",
                    authority="declaration_only", execution=False, mutation=False)
    if parsed.scheme == "model" and parsed.netloc and not parsed.query and not parsed.fragment:
        return dict(schema=SCHEMA, uri=text, kind="model", address_space="model",
                    alias=parsed.netloc + parsed.path, authority="declaration_only",
                    execution=False, mutation=False)
    raise ColumnContractError(f"invalid declared address: {uri!r}")


def _edge_field(edge: dict, *names):
    for name in names:
        if name in edge:
            return edge[name]
    return None


def validate_edge(edge: dict, catalog: dict | None = None) -> dict:
    """Validate one typed column edge. A successful result is still declaration-only."""
    catalog = catalog or load_catalog()
    problems: list[dict] = []
    source_uri = _edge_field(edge, "source_ref", "source")
    target_uri = _edge_field(edge, "target_ref", "target", "destination", "destination_ref")
    if not isinstance(source_uri, str) or not isinstance(target_uri, str):
        return dict(schema="gml-edge-validation/1", ok=False,
                    problems=[dict(code="endpoint", detail="source_ref and target_ref are required")],
                    authority="declaration_only", execution=False)
    try:
        source = resolve_column(source_uri, catalog)
    except ColumnContractError as error:
        problems.append(dict(code="source", detail=str(error)))
        source = None
    try:
        target = resolve_column(target_uri, catalog)
    except ColumnContractError as error:
        problems.append(dict(code="target", detail=str(error)))
        target = None
    if source and source.get("kind") != "column":
        problems.append(dict(code="source_direction", detail="source must be a column"))
    if target and target.get("kind") != "column":
        problems.append(dict(code="target_direction", detail="target must be a column"))
    if source and source.get("direction") != "output":
        problems.append(dict(code="source_direction", detail=f"{source_uri} is not an output column"))
    if target and target.get("direction") != "input":
        problems.append(dict(code="target_direction", detail=f"{target_uri} is not an input column"))
    edge_type = edge.get("type")
    if not isinstance(edge_type, str) or not edge_type.strip():
        problems.append(dict(code="type", detail="edge type is required"))
    else:
        try:
            _type_parts(edge_type)
        except ColumnContractError as error:
            problems.append(dict(code="type", detail=str(error)))
    rank = edge.get("rank")
    shape = edge.get("shape")
    if type(rank) is not int or rank < 0:
        problems.append(dict(code="rank", detail="edge rank must be a non-negative integer"))
    if not isinstance(shape, list) or len(shape) != rank:
        problems.append(dict(code="shape", detail="edge rank and shape must agree"))
    provenance = edge.get("provenance")
    if not isinstance(provenance, list) or not all(isinstance(item, str) for item in provenance):
        problems.append(dict(code="provenance", detail="edge provenance must be a string list"))
        provenance = []
    if source and isinstance(edge_type, str):
        if not _type_accepts(source["type"], edge_type):
            problems.append(dict(code="source_type", detail=f"{edge_type!r} is not produced by {source_uri}"))
        if type(rank) is int and rank != source["rank"]:
            problems.append(dict(code="source_rank", detail=f"{source_uri} declares rank {source['rank']}"))
        if isinstance(shape, list) and not _shape_matches(source["shape"], shape):
            problems.append(dict(code="source_shape", detail=f"{source_uri} shape is {source['shape']}"))
        if not set(source.get("provenance", ())).issubset(provenance):
            problems.append(dict(code="source_provenance", detail=f"{source_uri} provenance is incomplete"))
    if target and isinstance(edge_type, str):
        if not _type_accepts(target["type"], edge_type):
            problems.append(dict(code="target_type", detail=f"{edge_type!r} is not accepted by {target_uri}"))
        if type(rank) is int and rank != target["rank"]:
            problems.append(dict(code="target_rank", detail=f"{target_uri} declares rank {target['rank']}"))
        if isinstance(shape, list) and not _shape_matches(target["shape"], shape):
            problems.append(dict(code="target_shape", detail=f"{target_uri} shape is {target['shape']}"))
        if not set(target.get("provenance", ())).issubset(provenance):
            problems.append(dict(code="target_provenance", detail=f"{target_uri} provenance is incomplete"))
    return dict(schema="gml-edge-validation/1", ok=not problems, source=source_uri,
                target=target_uri, type=edge_type, rank=rank, shape=shape,
                provenance=provenance, problems=problems, authority="declaration_only",
                execution=False, mutation=False)
