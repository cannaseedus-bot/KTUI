"""Host-owned, read-only bindings for the generic Micronaut phase catalog.

The catalog is descriptive. This module is the separate host registration and admission boundary:
registered handlers are callable only with a host-issued, single-use admission bound to the exact
input bytes, URI, identity, and incoming declared edge. No handler accepts identity or authority from
the payload, and every binding is declared data-only.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Callable

import micronaut_registry
import gml_wiring

UTTERANCE = "kuhul://schema/utterance/v1"
# The relation row set the GML operators compute over: read-only data, never a graph mutation.
RELATIONS = "kuhul://schema/relations/v1"
CANDIDATES = "kuhul://schema/candidates/v1"
PROPOSITION = "kuhul://schema/proposition/v1"
ANSWER = "kuhul://schema/answer/v1"
GML_FILTER_URI = "micronaut://gml/relations/operators/filter"
GML_MAP_URI = "micronaut://gml/relations/operators/map"
GML_EDGE = {
    "source_ref": GML_FILTER_URI + "/columns/accepted",
    "target_ref": GML_MAP_URI + "/columns/input",
    "type": "Lane<relation>",
    "rank": 1,
    "shape": ["*"],
    "provenance": ["selection", "expansion"],
}
DENIED_KEYS = {"user", "user_id", "identity", "capabilities", "authority", "admitted",
               "execution", "mutation", "persistence"}
MAX_PAYLOAD_BYTES = 64 * 1024


class HandlerRefused(ValueError):
    pass


@dataclass(frozen=True)
class HandlerBinding:
    uri: str
    handler_id: str
    input_schema: str
    output_schema: str
    capability: str
    effect: str
    call: Callable


@dataclass(frozen=True)
class Admission:
    uri: str
    payload_digest: str
    identity: str
    incoming: str | None
    capability: str
    _owner: object
    _nonce: object


def _validate_payload(schema: str, payload: object) -> dict:
    if not isinstance(payload, dict) or payload.get("$schema") != schema:
        raise HandlerRefused("payload_schema_mismatch")
    def inspect(value):
        if isinstance(value, dict):
            if DENIED_KEYS.intersection(value):
                raise HandlerRefused("payload_contains_host_owned_fields")
            for child in value.values():
                inspect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                inspect(child)
        elif isinstance(value, float) and not math.isfinite(value):
            raise HandlerRefused("payload_contains_nonfinite_number")
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            raise HandlerRefused("payload_contains_non_json_value")
    inspect(payload)
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise HandlerRefused("payload_not_canonical_json") from error
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise HandlerRefused("payload_too_large")
    if schema == UTTERANCE:
        if not isinstance(payload.get("text"), str) or not payload["text"].strip():
            raise HandlerRefused("utterance_text_required")
        if len(payload["text"]) > 4096:
            raise HandlerRefused("utterance_too_large")
    elif schema in (CANDIDATES, PROPOSITION):
        if not isinstance(payload.get("query"), str) or len(payload["query"]) > 4096:
            raise HandlerRefused("query_required_or_too_large")
        items = payload.get("items")
        if not isinstance(items, list) or len(items) > 256 or any(not isinstance(row, dict) for row in items):
            raise HandlerRefused("items_must_be_a_bounded_object_array")
        required = ("category", "pattern", "captures") if schema == CANDIDATES else (
            "subject", "predicate", "value")
        for row in items:
            if schema == CANDIDATES and not isinstance(row.get("captures"), list):
                raise HandlerRefused("candidate_shape_invalid")
            for name in required:
                if name not in row:
                    raise HandlerRefused("item_shape_invalid")
            if schema == CANDIDATES and any(not isinstance(row.get(name), str)
                                            for name in ("category", "pattern")):
                raise HandlerRefused("candidate_shape_invalid")
            if schema == CANDIDATES and any(not isinstance(value, str)
                                            for value in row.get("captures", [])):
                raise HandlerRefused("candidate_shape_invalid")
            if schema == PROPOSITION and any(not isinstance(row.get(name), str)
                                             for name in ("subject", "predicate", "value")):
                raise HandlerRefused("proposition_shape_invalid")
    elif schema == RELATIONS:
        if not isinstance(payload.get("query"), str) or len(payload["query"]) > 4096:
            raise HandlerRefused("query_required_or_too_large")
        items = payload.get("items")
        if not isinstance(items, list) or len(items) > 256 or any(not isinstance(row, dict) for row in items):
            raise HandlerRefused("items_must_be_a_bounded_object_array")
        for row in items:
            if not isinstance(row.get("id"), str) or not isinstance(row.get("predicate"), str):
                raise HandlerRefused("relation_row_shape_invalid")
            if "value" not in row or not isinstance(row.get("accepted"), bool):
                raise HandlerRefused("relation_row_shape_invalid")
    elif schema == ANSWER:
        if not isinstance(payload.get("text"), str) or not isinstance(payload.get("status"), str):
            raise HandlerRefused("answer_shape_invalid")
    elif schema == UTTERANCE:
        if not isinstance(payload.get("text"), str) or not payload["text"].strip():
            raise HandlerRefused("utterance_text_required")
    else:
        raise HandlerRefused("unsupported_input_schema")
    return payload


def _aiml(payload: dict, identity: str) -> dict:
    import phase_resolve
    plan = phase_resolve.resolve_aiml(payload["text"], user=identity)
    pop = plan["phases"]["Pop"]
    return {"$schema": CANDIDATES, "query": payload["text"],
            "items": [dict(category=row["category"], pattern=row["pattern"],
                           captures=list(row["captures"]), redirect=bool(row["redirect"]),
                           directive=bool(row["directive"])) for row in pop["matched"]],
            "status": "HANDLER_INVOKED"}


def _relations(payload: dict, identity: str) -> dict:
    import compose
    contract = compose.load()
    if not contract.get("ok"):
        raise HandlerRefused("composition_contract_unavailable")
    rows = compose.retrieve(identity, payload["query"], contract["settings"])
    return {"$schema": PROPOSITION, "query": payload["query"],
            "items": [dict(row["relation"], score=row["score"]) for row in rows],
            "status": "HANDLER_INVOKED"}


def _memory(payload: dict, identity: str) -> dict:
    import user_memory
    graph = user_memory.graph(identity)
    check = user_memory.validate(graph)
    if not check.get("ok"):
        raise HandlerRefused("memory_graph_validation_failed")
    nodes = {node["id"]: node for node in graph["nodes"]}
    items = []
    for edge in graph["edges"]:
        source, target = nodes[edge["source"]], nodes[edge["target"]]
        if source.get("kind") != "entity" or target.get("kind") != "fact":
            continue
        ref = source.get("ref", "")
        subject = ref.split(":", 1)[1] if ":" in ref else ""
        items.append(dict(subject=subject, predicate=edge["relation"], value=target.get("value", ""),
                          evidence="derived_user_memory_graph"))
    event_ids = {}
    for row in user_memory.events(identity):
        event = row.get("payload") or {}
        if event.get("type") == "fact_asserted":
            event_ids[(event.get("subject"), event.get("predicate"))] = row.get("event_id")
    for item in items:
        item["event_id"] = event_ids.get((item["subject"], item["predicate"]))
    return {"$schema": PROPOSITION, "query": payload["query"], "items": items,
            "graph_id": graph["graph_id"], "graph_validation": check,
            "status": "HANDLER_INVOKED"}


def _eliza(payload: dict, identity: str) -> dict:
    import phase_resolve
    fields = phase_resolve.eliza_fields(payload["query"])
    return {"$schema": UTTERANCE, "text": payload["query"], "fields": fields,
            "status": "HANDLER_INVOKED"}


def _compose(payload: dict, identity: str) -> dict:
    import compose
    contract = compose.load()
    if not contract.get("ok"):
        raise HandlerRefused("composition_contract_unavailable")
    plan = compose.compose(payload["items"], contract["settings"])
    verification = compose.verify(plan, payload["items"], user=identity)
    ok = bool(plan.get("ok") and verification.get("ok"))
    return {"$schema": ANSWER, "query": payload["query"],
            "text": plan.get("paragraph", "") if ok else "",
            "status": "VERIFIED_READ_RESULT" if ok else "INSUFFICIENT_EVIDENCE",
            "verification": verification, "evidence_refs": list(plan.get("used") or [])}


def _gml_filter(payload: dict, identity: str) -> dict:
    """Keep the accepted relations. Pure: same query, fewer rows, no mutation."""
    rows = [dict(row) for row in payload["items"] if row.get("accepted") is True]
    return {"$schema": RELATIONS, "query": payload["query"], "column": "accepted",
            "items": rows, "status": "HANDLER_INVOKED", "operator": "filter"}


def _gml_map(payload: dict, identity: str) -> dict:
    """Project each row to an upper-cased predicate. Pure: same rows, one added column."""
    rows = [dict(row, mapped=str(row.get("predicate", "")).upper()) for row in payload["items"]]
    return {"$schema": RELATIONS, "query": payload["query"], "column": "mapped",
            "items": rows, "status": "HANDLER_INVOKED", "operator": "map"}


def gml_chain_contract() -> dict:
    """The typed FILTER.accepted -> MAP.input contract, still declaration-only."""
    result = gml_wiring.validate_edge_record(GML_EDGE)
    return dict(schema="kuhul://gml/chain/filter-map/v1", chain="filter_to_map",
                source=GML_FILTER_URI, target=GML_MAP_URI, edge=GML_EDGE,
                validation=result, authority="declaration_only", admitted=False,
                execution=False, mutation=False, persistence=False)


def bindings() -> dict[str, HandlerBinding]:
    """Explicit handler allowlist; unimplemented declarations stay unbound."""
    rows = (
        HandlerBinding("micronaut://v1/aiml", "phase_resolve.resolve_aiml.pop.v1", UTTERANCE,
                       CANDIDATES, "graph.relations.read", "read_only", _aiml),
        HandlerBinding("micronaut://v1/relations", "compose.retrieve.v1", CANDIDATES,
                       PROPOSITION, "graph.relations.read", "read_only", _relations),
        HandlerBinding("micronaut://v1/memory", "user_memory.graph.read.v1", CANDIDATES,
                       PROPOSITION, "graph.relations.read", "read_only", _memory),
        HandlerBinding("micronaut://v1/eliza", "phase_resolve.eliza_fields.v1", PROPOSITION,
                       UTTERANCE, "graph.relations.read", "read_only", _eliza),
        HandlerBinding("micronaut://v1/compose", "compose.compose_verify.v1", PROPOSITION,
                       ANSWER, "graph.relations.read", "read_only", _compose),
        # The first two executable GML operators: registered handlers, read-only computation over supplied rows.
        HandlerBinding("micronaut://gml/relations/operators/filter", "gml.relations.filter.v1",
                       RELATIONS, RELATIONS, "graph.relations.read", "read_only", _gml_filter),
        HandlerBinding("micronaut://gml/relations/operators/map", "gml.relations.map.v1",
                       RELATIONS, RELATIONS, "graph.relations.read", "read_only", _gml_map),
    )
    return {row.uri: row for row in rows}


GRAPH_THEORY_BINDING = HandlerBinding(
    "micronaut:GRAPH-THEORY", "micronaut.graph_executor.execute_graph_query",
    "kuhul://schema/graph-query/v1", "kuhul://schema/graph-query-proposal/v1",
    "read_graph_inventory", "read_only", None)


class GraphTheoryHost:
    """Host-admitted adapter for the semantic Graph Theory Micronaut.

    This handler reads allowlisted repository GML and emits a DATA_ONLY proposal. It does not dispatch
    tools or mutate data. The callback is supplied only by the trusted host, never by the request.
    """
    def __init__(self, policy: Callable[[HandlerBinding, dict], bool]):
        self.policy = policy
        self.invocations: list[dict] = []

    def invoke(self, payload: dict) -> dict:
        if not isinstance(payload, dict) or payload.get("$schema") != GRAPH_THEORY_BINDING.input_schema:
            raise HandlerRefused("graph_query_schema_mismatch")
        if DENIED_KEYS.intersection(payload) or set(payload) - {"$schema", "query"}:
            raise HandlerRefused("graph_query_fields_invalid")
        query = payload.get("query")
        if not isinstance(query, dict):
            raise HandlerRefused("graph_query_object_required")
        try:
            encoded = json.dumps(query, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            raise HandlerRefused("graph_query_not_json") from error
        if len(encoded) > 8 * 1024:
            raise HandlerRefused("graph_query_too_large")
        if DENIED_KEYS.intersection(query):
            raise HandlerRefused("graph_query_contains_host_fields")
        if self.policy(GRAPH_THEORY_BINDING, query) is not True:
            raise HandlerRefused("graph_host_admission_denied")
        import micronaut.graph_executor as graph_executor
        result = graph_executor.execute_graph_query(query)
        if result.get("schema") != GRAPH_THEORY_BINDING.output_schema:
            raise HandlerRefused("graph_query_output_contract_mismatch")
        receipt = dict(handler=GRAPH_THEORY_BINDING.handler_id,
                       micronaut=GRAPH_THEORY_BINDING.uri,
                       input_schema=GRAPH_THEORY_BINDING.input_schema,
                       output_schema=GRAPH_THEORY_BINDING.output_schema,
                       status="HANDLER_INVOKED", admission="host_read_only_policy",
                       effects=dict(tool_dispatch=False, mutation=False, persistence=False))
        self.invocations.append(receipt)
        return dict(payload=result, invocation=receipt, admitted=True,
                    authority="DATA_ONLY", effects=receipt["effects"])


class HandlerHost:
    """One host invocation context with a trusted identity, grants, and explicit admission policy."""
    # Where a turn may begin. Only the head of the operator chain joins the AIML entrypoint: the second
    # operator is reachable exclusively through its declared edge, which is what makes the edge meaningful.
    ENTRYPOINTS = {"micronaut://v1/aiml", "micronaut://gml/relations/operators/filter"}

    def __init__(self, *, identity: str, granted: set[str], policy: Callable[[HandlerBinding, dict], bool]):
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError("a host-resolved identity is required")
        self.identity = identity
        self.granted = set(granted)
        self.policy = policy
        self.registry = micronaut_registry.load()
        self.bindings = bindings()
        self._used: set[object] = set()
        self.invocations: list[dict] = []

    def admit(self, uri: str, payload: dict, *, from_uri: str | None = None) -> Admission:
        binding = self.bindings.get(uri)
        if binding is None:
            raise HandlerRefused("handler_not_registered")
        declaration = self.registry.get("by_uri", {}).get(uri)
        if not self.registry.get("ok") or declaration is None:
            raise HandlerRefused("micronaut_declaration_invalid_or_missing")
        if (binding.input_schema != declaration["input_schema"] or
                binding.output_schema != declaration["output_schema"] or
                binding.capability not in declaration["capabilities"]):
            raise HandlerRefused("handler_contract_mismatch")
        payload = _validate_payload(binding.input_schema, payload)
        if binding.capability not in self.granted:
            raise HandlerRefused("capability_not_granted")
        if from_uri is None:
            if uri not in self.ENTRYPOINTS:
                raise HandlerRefused("not_an_admitted_entrypoint")
        else:
            route = micronaut_registry.route(self.registry, declaration["input_schema"],
                                             from_uri=from_uri, granted=self.granted)
            if route.get("refused"):
                raise HandlerRefused(route["refused"])
            # The host may select any explicitly declared authorized branch; undeclared targets
            # remain impossible. The generic route helper's default first edge is for display only.
            if not any(edge["target"] == uri for edge in route.get("candidates", [])):
                raise HandlerRefused("target_not_declared_by_edge")
        if binding.effect != "read_only" or self.policy(binding, payload) is not True:
            raise HandlerRefused("host_admission_denied")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return Admission(uri=uri, payload_digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                         identity=self.identity, incoming=from_uri, capability=binding.capability,
                         _owner=self, _nonce=object())

    def invoke(self, admission: Admission, payload: dict) -> dict:
        if not isinstance(admission, Admission) or admission._owner is not self:
            raise HandlerRefused("foreign_admission")
        if admission._nonce in self._used:
            raise HandlerRefused("admission_already_consumed")
        payload = _validate_payload(self.bindings[admission.uri].input_schema, payload)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if digest != admission.payload_digest:
            raise HandlerRefused("admitted_payload_changed")
        if admission.identity != self.identity or admission.capability not in self.granted:
            raise HandlerRefused("admission_context_changed")
        self._used.add(admission._nonce)
        binding = self.bindings[admission.uri]
        result = binding.call(payload, self.identity)
        if not isinstance(result, dict) or result.get("$schema") != binding.output_schema:
            raise HandlerRefused("handler_output_schema_mismatch")
        _validate_payload(binding.output_schema, result)
        if result.get("status") != "HANDLER_INVOKED":
            # The compose adapter uses a finer result status while still proving that it ran.
            if admission.uri != "micronaut://v1/compose" or result.get("status") not in (
                    "VERIFIED_READ_RESULT", "INSUFFICIENT_EVIDENCE"):
                raise HandlerRefused("handler_invocation_status_missing")
        record = dict(handler= binding.handler_id, uri=binding.uri, input_schema=binding.input_schema,
                      output_schema=binding.output_schema, incoming=admission.incoming,
                      capability=admission.capability, status="HANDLER_INVOKED",
                      effects=dict(graph_write=False, mutation=False, persistence=False))
        self.invocations.append(record)
        return dict(payload=result, invocation=record, admitted=True,
                    authority="host_read_only", effects=record["effects"])
