"""Conformance guards for declaration-to-host binding and real read-only invocation."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import micronaut_host_handlers as handlers  # noqa: E402
import micronaut_audit  # noqa: E402
import micronaut_server  # noqa: E402
import mcp_host  # noqa: E402


def allow_read(binding, payload):
    return binding.effect == "read_only" and "graph.relations.read" == binding.capability


class HostHandlerTests(unittest.TestCase):
    def setUp(self):
        self.host = handlers.HandlerHost(identity="micronaut-conformance-no-data",
                                         granted={"graph.relations.read"}, policy=allow_read)

    def test_every_phase_catalog_entry_has_an_exact_typed_host_binding(self):
        self.assertTrue(self.host.registry["ok"], self.host.registry["problems"])
        self.assertEqual(set(self.host.bindings), set(self.host.registry["by_uri"]))
        for uri, binding in self.host.bindings.items():
            declaration = self.host.registry["by_uri"][uri]
            self.assertEqual(binding.input_schema, declaration["input_schema"])
            self.assertEqual(binding.output_schema, declaration["output_schema"])
            self.assertIn(binding.capability, declaration["capabilities"])
            self.assertEqual(binding.effect, "read_only")

    def test_aiml_to_memory_to_compose_invokes_registered_handlers(self):
        utterance = {"$schema": handlers.UTTERANCE, "text": "hello"}
        aiml = self.host.invoke(self.host.admit("micronaut://v1/aiml", utterance), utterance)
        self.assertEqual(aiml["payload"]["$schema"], handlers.CANDIDATES)
        self.assertEqual(aiml["invocation"]["handler"], "phase_resolve.resolve_aiml.pop.v1")
        self.assertEqual(aiml["invocation"]["status"], "HANDLER_INVOKED")

        candidate_payload = aiml["payload"]
        memory = self.host.invoke(
            self.host.admit("micronaut://v1/memory", candidate_payload,
                            from_uri="micronaut://v1/aiml"), candidate_payload)
        self.assertEqual(memory["payload"]["$schema"], handlers.PROPOSITION)
        self.assertEqual(memory["invocation"]["handler"], "user_memory.graph.read.v1")
        self.assertEqual(memory["payload"]["graph_validation"]["ok"], True)

        proposition_payload = memory["payload"]
        answer = self.host.invoke(
            self.host.admit("micronaut://v1/compose", proposition_payload,
                            from_uri="micronaut://v1/memory"), proposition_payload)
        self.assertEqual(answer["payload"]["$schema"], handlers.ANSWER)
        self.assertEqual(answer["payload"]["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual([item["uri"] for item in self.host.invocations],
                         ["micronaut://v1/aiml", "micronaut://v1/memory", "micronaut://v1/compose"])
        for item in self.host.invocations:
            self.assertFalse(item["effects"]["graph_write"])
            self.assertFalse(item["effects"]["mutation"])
            self.assertFalse(item["effects"]["persistence"])

    def test_all_registered_handlers_invoke_against_their_declared_contracts(self):
        utterance = {"$schema": handlers.UTTERANCE, "text": "hello"}
        aiml = self.host.invoke(self.host.admit("micronaut://v1/aiml", utterance), utterance)["payload"]
        relation = self.host.invoke(
            self.host.admit("micronaut://v1/relations", aiml, from_uri="micronaut://v1/aiml"), aiml)["payload"]
        memory = self.host.invoke(
            self.host.admit("micronaut://v1/memory", aiml, from_uri="micronaut://v1/aiml"), aiml)["payload"]
        eliza = self.host.invoke(
            self.host.admit("micronaut://v1/eliza", relation, from_uri="micronaut://v1/relations"), relation)["payload"]
        compose_input = dict(memory, query="missing")
        composed = self.host.invoke(
            self.host.admit("micronaut://v1/compose", compose_input, from_uri="micronaut://v1/memory"),
            compose_input)["payload"]
        relation_input = {
            "$schema": handlers.RELATIONS,
            "query": "typed edge",
            "items": [
                {"id": "r1", "predicate": "likes", "value": "walks", "accepted": True},
                {"id": "r2", "predicate": "owns", "value": "cat", "accepted": False},
            ],
        }
        filtered = self.host.invoke(
            self.host.admit(handlers.GML_FILTER_URI, relation_input), relation_input)["payload"]
        mapped = self.host.invoke(
            self.host.admit(handlers.GML_MAP_URI, filtered, from_uri=handlers.GML_FILTER_URI),
            filtered)["payload"]
        outputs = {
            "micronaut://v1/aiml": aiml,
            "micronaut://v1/relations": relation,
            "micronaut://v1/memory": memory,
            "micronaut://v1/eliza": eliza,
            "micronaut://v1/compose": composed,
            handlers.GML_FILTER_URI: filtered,
            handlers.GML_MAP_URI: mapped,
        }
        for uri, payload in outputs.items():
            with self.subTest(uri=uri):
                self.assertEqual(payload["$schema"], self.host.bindings[uri].output_schema)
        self.assertEqual({row["uri"] for row in self.host.invocations}, set(self.host.bindings))
        self.assertEqual(mapped["items"][0]["mapped"], "LIKES")

    def test_static_audit_distinguishes_generic_handlers_and_local_graph_theory_handler(self):
        audit = micronaut_audit.report()
        phase = audit["phase_engine_registry"]
        self.assertEqual(len(phase["host_handler_bindings"]), len(handlers.bindings()))
        self.assertTrue(all(row["host_handler_registered"] and row["input_contract_matches"] and
                            row["output_contract_matches"] for row in phase["host_handler_bindings"]))
        self.assertEqual(phase["runtime_handler_invocation"], "not_established_by_static_audit")
        graph = audit["graph_theory"]
        self.assertTrue(graph["host_handler_registered"])
        self.assertTrue(graph["entry_point_callable_present"])
        self.assertEqual(graph["unresolved_program_refs"], [])
        self.assertFalse(graph["invocation_observed"],
                         "static audit must not claim runtime invocation")
        semantic = audit["semantic_registry"]
        self.assertEqual(semantic["declared_count"], 13)
        self.assertEqual(semantic["entries_with_host_handler_binding"], 1)
        self.assertEqual(semantic["entries_with_invocation_observed"], 0)
        bound = [row["id"] for row in semantic["entries"] if row["host_handler_registered"]]
        self.assertEqual(bound, ["micronaut:GRAPH-THEORY"])
        unresolved_programs = {
            row["id"] for row in semantic["entries"]
            if row["program_reference_status"] == "unresolved"
        }
        self.assertEqual(semantic["entries_with_unresolved_program_references"], 6)
        self.assertEqual(unresolved_programs, {
            "micronaut:ADVISOR", "micronaut:CFPC", "micronaut:CODEX",
            "micronaut:ELIZA", "micronaut:LEARNING", "micronaut:QUESTION_ENGINE",
        })
        self.assertTrue(all(not row["host_handler_registered"] for row in semantic["entries"]
                            if row["program_reference_status"] == "unresolved"))
        for route, status in audit["css_binding_declarations"].items():
            with self.subTest(route=route):
                self.assertIn(status["dispatch"], ("not_invoked", "host_controlled_not_invoked"))
                self.assertNotEqual(status["dispatch"], "invoked",
                                    "static declarations are not runtime invocation evidence")

    def test_handler_is_not_called_when_host_admission_fails(self):
        host = handlers.HandlerHost(identity="test-user", granted={"graph.relations.read"},
                                    policy=lambda *_: False)
        with self.assertRaises(handlers.HandlerRefused):
            host.admit("micronaut://v1/aiml", {"$schema": handlers.UTTERANCE, "text": "hello"})
        self.assertEqual(host.invocations, [])

    def test_missing_capability_and_undeclared_transition_are_refused(self):
        host = handlers.HandlerHost(identity="test-user", granted=set(), policy=lambda *_: True)
        utterance = {"$schema": handlers.UTTERANCE, "text": "hello"}
        with self.assertRaisesRegex(handlers.HandlerRefused, "capability_not_granted"):
            host.admit("micronaut://v1/aiml", utterance)

        host = handlers.HandlerHost(identity="test-user", granted={"graph.relations.read"},
                                    policy=lambda *_: True)
        proposition = {"$schema": handlers.PROPOSITION, "query": "hello", "items": []}
        with self.assertRaisesRegex(handlers.HandlerRefused, "no_declared_edge"):
            host.admit("micronaut://v1/compose", proposition, from_uri="micronaut://v1/aiml")

    def test_identity_and_authority_cannot_be_asserted_or_changed_in_payload(self):
        host = handlers.HandlerHost(identity="trusted-user", granted={"graph.relations.read"},
                                    policy=lambda *_: True)
        forged = {"$schema": handlers.UTTERANCE, "text": "hello", "user_id": "other-user"}
        with self.assertRaisesRegex(handlers.HandlerRefused, "host_owned_fields"):
            host.admit("micronaut://v1/aiml", forged)
        payload = {"$schema": handlers.UTTERANCE, "text": "hello"}
        ticket = host.admit("micronaut://v1/aiml", payload)
        changed = dict(payload, text="different")
        with self.assertRaisesRegex(handlers.HandlerRefused, "admitted_payload_changed"):
            host.invoke(ticket, changed)

    def test_ticket_is_single_use_and_bound_to_its_host(self):
        payload = {"$schema": handlers.UTTERANCE, "text": "hello"}
        first = handlers.HandlerHost(identity="user-a", granted={"graph.relations.read"}, policy=allow_read)
        ticket = first.admit("micronaut://v1/aiml", payload)
        first.invoke(ticket, payload)
        with self.assertRaisesRegex(handlers.HandlerRefused, "already_consumed"):
            first.invoke(ticket, payload)
        second = handlers.HandlerHost(identity="user-a", granted={"graph.relations.read"}, policy=allow_read)
        with self.assertRaisesRegex(handlers.HandlerRefused, "foreign_admission"):
            second.invoke(ticket, payload)

    def test_host_engine_uses_session_identity_not_payload_identity(self):
        class App:
            user_id = "engine-session-user"

            def granted_capabilities(self):
                return {"graph.relations.read"}

        engine = micronaut_server.Engine(app=App())
        payload = {"$schema": handlers.UTTERANCE, "text": "hello"}
        result = engine.invoke_micronaut("micronaut://v1/aiml", payload)
        self.assertEqual(result["invocation"]["handler"], "phase_resolve.resolve_aiml.pop.v1")
        self.assertEqual(engine.last_micronaut_invocation, result["invocation"])
        self.assertEqual(result["payload"]["$schema"], handlers.CANDIDATES)
        self.assertFalse(result["effects"]["graph_write"])
        self.assertFalse(result["effects"]["mutation"])
        self.assertFalse(result["effects"]["persistence"])

    def test_gml_filter_map_chain_reuses_engine_and_preserves_typed_edge(self):
        class App:
            user_id = "engine-session-user"

            def granted_capabilities(self):
                return {"graph.relations.read"}

        engine = micronaut_server.Engine(app=App())
        payload = {
            "$schema": handlers.RELATIONS,
            "query": "dogs",
            "items": [
                {"id": "1", "predicate": "likes", "value": "walks", "accepted": True},
                {"id": "2", "predicate": "owns", "value": "cat", "accepted": False},
            ],
        }
        result = engine.invoke_gml_filter_map(payload)
        self.assertEqual(result["status"], "VERIFIED_READ_RESULT")
        self.assertTrue(result["engine_reused"])
        self.assertTrue(result["typed_edge"]["validation"]["ok"])
        self.assertEqual([row["handler"] for row in result["invocations"]],
                         ["gml.relations.filter.v1", "gml.relations.map.v1"])
        self.assertEqual(result["payload"]["items"][0]["mapped"], "LIKES")
        self.assertEqual(result["payload"]["items"][0]["accepted"], True)

    def test_invalid_gml_transition_is_refused_before_downstream_invocation(self):
        payload = {"$schema": handlers.RELATIONS, "query": "x", "items": []}
        with self.assertRaisesRegex(handlers.HandlerRefused, "no_declared_edge"):
            self.host.admit(handlers.GML_MAP_URI, payload, from_uri="micronaut://v1/relations")
        self.assertEqual(self.host.invocations, [])

    def test_gml_handler_failure_reaches_chen_and_leaves_xul_open(self):
        class App:
            user_id = "engine-session-user"

            def granted_capabilities(self):
                return {"graph.relations.read"}

        engine = micronaut_server.Engine(app=App())
        payload = {"$schema": handlers.RELATIONS, "query": "dogs", "items": []}
        original = handlers._gml_map
        try:
            handlers._gml_map = lambda *_: (_ for _ in ()).throw(RuntimeError("map failed"))
            result = engine.invoke_gml_filter_map(payload)
        finally:
            handlers._gml_map = original
        self.assertEqual(result["status"], "REJECTED")
        self.assertEqual(result["phases"][-2]["phase"], "Ch'en")
        self.assertEqual(result["phases"][-1]["status"], "NOT_CLOSED")
        self.assertEqual(len(result["invocations"]), 1)

    def test_mcp_reports_the_typed_chain_without_admitting_it(self):
        report = mcp_host.gml_chain_status()
        self.assertTrue(report["validation"]["ok"])
        self.assertFalse(report["admitted"])
        self.assertFalse(report["execution"])
        handlers_report = mcp_host.list_handlers()
        uris = {row["uri"] for row in handlers_report["handlers"]}
        self.assertIn(handlers.GML_FILTER_URI, uris)
        self.assertIn(handlers.GML_MAP_URI, uris)


if __name__ == "__main__":
    unittest.main()
