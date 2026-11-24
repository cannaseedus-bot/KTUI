"""M50: the runtime projection - one read-only tree over the registries, and the questions it answers.

Two properties under test:

**Read-only.** Every node says `declaration_only`, and nothing in the projection can start a model, change
a binding or admit a proposal. The projection is a view; the registries and XCFE remain authoritative.

**Built from the live registries.** Counts and edges are checked against the phase manifests, the micronaut
registry, the model declarations and the evidence ledger - not against a fixture copy of them.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evidence_record  # noqa: E402
import micronaut_registry  # noqa: E402
import model_lifecycle  # noqa: E402
import runtime_tree  # noqa: E402


class ProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = runtime_tree.projection()

    def kinds(self) -> dict:
        counts: dict[str, int] = {}
        for node in self.tree["nodes"]:
            counts[node["kind"]] = counts.get(node["kind"], 0) + 1
        return counts

    def test_the_tree_covers_every_registry(self):
        counts = self.kinds()
        self.assertEqual(counts.get("runtime"), 1)
        self.assertEqual(counts.get("phase"), 6, "one node per phase manifest")
        self.assertEqual(counts.get("micronaut"), len(micronaut_registry.load()["list"]))
        self.assertEqual(counts.get("model"), len(model_lifecycle.load()["by_name"]))
        self.assertGreaterEqual(counts.get("corpus"), 4)
        self.assertEqual(counts.get("evidence"), 1)

    def test_every_node_is_read_only(self):
        for node in self.tree["nodes"]:
            self.assertEqual(node["authority"], "declaration_only", node["id"])
        self.assertFalse(self.tree["execution"])
        self.assertFalse(self.tree["mutation"])

    def test_the_phase_chain_is_walkable(self):
        chain = [(edge["source"], edge["target"]) for edge in self.tree["edges"]
                 if edge["relation"] == "precedes"]
        self.assertTrue(chain, "the manifests declare next links")
        for source, target in chain:
            self.assertTrue(source.startswith("phase://"))
            self.assertTrue(target.startswith("phase://"))

    def test_the_model_bindings_match_the_router(self):
        bindings = {(edge["source"], edge["target"]) for edge in self.tree["edges"]
                    if edge["relation"] == "binds_to"}
        router = model_lifecycle.load()["router"]
        expected = {(micronaut, f"model://{model}")
                    for micronaut, model in router["routing"].items()}
        self.assertEqual(bindings, expected)

    def test_the_escalation_order_is_visible(self):
        preference = runtime_tree.query(self.tree, "preference://plan")
        self.assertIsNotNone(preference)
        self.assertEqual(preference["fields"]["order"], ["planner", "advisor", "worker"])

    def test_the_evidence_ledger_reports_its_state(self):
        node = runtime_tree.query(self.tree, "evidence://ledger")
        records = evidence_record.load()
        self.assertEqual(node["fields"]["records"], len(records))
        self.assertEqual(node["fields"]["chain_ok"], bool(evidence_record.verify().get("ok")))

    def test_an_unknown_node_is_none(self):
        self.assertIsNone(runtime_tree.query(self.tree, "runtime://nothing"))

    def test_the_projection_is_deterministic(self):
        import json
        again = runtime_tree.projection()
        self.assertEqual(json.dumps(again["nodes"], sort_keys=True),
                         json.dumps(self.tree["nodes"], sort_keys=True))

    def test_the_render_names_the_authority(self):
        text = runtime_tree.render(self.tree)
        self.assertIn("read-only projection", text)
        self.assertIn("runtime://green-screen/v1", text)


class QueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = runtime_tree.projection()

    def test_neighbours_filters_by_relation(self):
        neighbours = runtime_tree.neighbours(self.tree, "micronaut://v1/compose", "binds_to")
        self.assertEqual([edge["target"] for edge in neighbours["outgoing"]], ["model://planner"])

    def test_selection_explanation_uses_live_health_and_features(self):
        explanation = runtime_tree.explain_selection(self.tree, "micronaut://v1/compose")
        self.assertTrue(explanation["ok"], explanation)
        self.assertEqual(explanation["selected"], "planner")
        self.assertIn("health", explanation)
        self.assertFalse(explanation["admitted"], "an explanation is not an admission")

    def test_a_feature_requirement_explains_the_switch(self):
        router = model_lifecycle.load()["router"]
        binding = __import__("model_router").select(
            router, "micronaut://v1/aiml", features=("tools",),
            probes={name: {"ok": True} for name in router["models"]})
        self.assertEqual(binding["selected"], "advisor")
        self.assertIn("missing_features", [item["reason"] for item in binding["rejected"]])

    def test_who_binds_to_the_advisor_is_answerable(self):
        users = runtime_tree.users_of(self.tree, "advisor")
        # nothing declares the advisor as a binding any more: it is the escalation target
        self.assertEqual(users, [])
        preference = runtime_tree.query(self.tree, "preference://plan")
        self.assertIn("advisor", preference["fields"]["order"])


if __name__ == "__main__":
    unittest.main()
