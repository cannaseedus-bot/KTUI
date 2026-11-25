"""Graph Theory Micronaut query, admission, and loopback API conformance."""
import http.client
import json
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import micronaut_audit  # noqa: E402
import micronaut_host_handlers as host_handlers  # noqa: E402
import micronaut_server  # noqa: E402
from micronaut.graph_executor import GraphQueryError, execute_graph_query, parse_gml  # noqa: E402


def allow_graph_read(binding, query):
    return (binding.uri == "micronaut:GRAPH-THEORY" and
            binding.capability == "read_graph_inventory" and binding.effect == "read_only")


class GraphTheoryMicronautTests(unittest.TestCase):
    def test_manifest_inventory_is_bounded_and_only_lists_existing_gml(self):
        result = execute_graph_query({"operation": "inventory"})
        self.assertEqual(result["schema"], host_handlers.GRAPH_THEORY_BINDING.output_schema)
        self.assertTrue(result["graphs"])
        for graph in result["graphs"]:
            self.assertTrue((ROOT / graph["source_ref"]).is_file())
            self.assertLessEqual(graph["bytes"], 4 * 1024 * 1024)

    def test_q3_statistics_and_quoted_zero_padded_labels_are_preserved(self):
        stats = execute_graph_query({"operation": "stats", "graph_id": "hypercube_q3"})
        self.assertEqual((stats["node_count"], stats["edge_count"], stats["degree_min"],
                          stats["degree_max"]), (8, 16, 4, 4))
        graph_text = (ROOT / "data/hypercube_Q3.gml").read_text(encoding="utf-8")
        graph = parse_gml(graph_text)
        self.assertEqual(graph["nodes"]["0"]["label"], "000")
        neighbors = execute_graph_query({"operation": "neighbors", "graph_id": "hypercube_q3",
                                         "source": "0", "depth": 1})
        self.assertEqual({row["node"]["label"] for row in neighbors["neighbors"]},
                         {"001", "010", "100", "111"})

    def test_path_query_is_topological_and_does_not_claim_truth_or_permission(self):
        result = execute_graph_query({"operation": "path", "graph_id": "hypercube_q3",
                                      "source": "0", "target": "7"})
        self.assertEqual(result["distance"], 1)
        self.assertEqual(result["path"][0]["label"], "000")
        self.assertEqual(result["path"][-1]["label"], "111")
        self.assertFalse(result["topology_verified"])
        self.assertFalse(result["truth_claim"])
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["persistence"])

    def test_unknown_graphs_operations_fields_and_bounds_fail_closed(self):
        bad = (
            {"operation": "stats", "graph_id": "../../.env"},
            {"operation": "shell", "graph_id": "hypercube_q3"},
            {"operation": "stats", "graph_id": "hypercube_q3", "path": "C:/secret"},
            {"operation": "neighbors", "graph_id": "hypercube_q3", "source": "0", "depth": 99},
            {"operation": "match", "graph_id": "hypercube_q3", "term": ""},
        )
        for query in bad:
            with self.subTest(query=query), self.assertRaises(GraphQueryError):
                execute_graph_query(query)

    def test_malformed_graph_structure_is_rejected(self):
        malformed = (
            "graph [ node [ id 1 ] node [ id 1 ] ]",
            "graph [ node [ id 1 ] edge [ source 1 target 2 ] ]",
            'graph [ node [ id 1 label "unterminated ] ]',
        )
        for text in malformed:
            with self.subTest(text=text), self.assertRaises(GraphQueryError):
                parse_gml(text)

    def test_host_policy_is_required_and_receipt_is_separate_from_proposal(self):
        payload = {"$schema": host_handlers.GRAPH_THEORY_BINDING.input_schema,
                   "query": {"operation": "stats", "graph_id": "hypercube_q3"}}
        denied = host_handlers.GraphTheoryHost(policy=lambda *_: False)
        with self.assertRaisesRegex(host_handlers.HandlerRefused, "admission_denied"):
            denied.invoke(payload)
        self.assertEqual(denied.invocations, [])

        host = host_handlers.GraphTheoryHost(policy=allow_graph_read)
        result = host.invoke(payload)
        self.assertEqual(result["invocation"]["handler"],
                         "micronaut.graph_executor.execute_graph_query")
        self.assertEqual(result["payload"]["schema"],
                         host_handlers.GRAPH_THEORY_BINDING.output_schema)
        self.assertTrue(result["admitted"])
        self.assertFalse(result["effects"]["tool_dispatch"])

    def test_engine_exposes_declared_graph_api_on_loopback(self):
        class App:
            user_id = "unused-for-public-static-gml"

            def granted_capabilities(self):
                return {"graph.relations.read"}

        engine = micronaut_server.Engine(app=App())
        server = micronaut_server.serve(port=0, engine=engine, block=False)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            body = json.dumps({"key": "graph-theory.query",
                               "query": {"operation": "stats", "graph_id": "hypercube_q3"}})
            connection.request("POST", "/api/atomic/call", body=body,
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            result = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(result["payload"]["node_count"], 8)
            self.assertEqual(engine.last_graph_invocation["handler"],
                             "micronaut.graph_executor.execute_graph_query")

            connection.request("POST", "/api/atomic/call",
                               body=json.dumps({"key": "unknown", "query": {}}),
                               headers={"Content-Type": "application/json"})
            refused = connection.getresponse()
            refused.read()
            self.assertEqual(refused.status, 404)

            connection.request("GET", "/api/health")
            health = connection.getresponse()
            self.assertEqual(health.status, 200)
            self.assertEqual(json.loads(health.read().decode("utf-8"))["micronaut"],
                             "micronaut:GRAPH-THEORY")
            connection.close()
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

    def test_static_audit_resolves_graph_theory_program_and_binds_its_entry_point(self):
        audit = micronaut_audit.report()
        self.assertTrue(audit["graph_theory"]["host_handler_registered"])
        self.assertTrue(audit["graph_theory"]["entry_point_callable_present"])
        self.assertEqual(audit["graph_theory"]["unresolved_program_refs"], [])
        self.assertFalse(audit["graph_theory"]["invocation_observed"],
                         "static audit remains separate from runtime invocation receipts")


if __name__ == "__main__":
    unittest.main()
