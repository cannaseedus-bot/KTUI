"""M40: the micronaut registry - typed agents, typed edges, and three independent guarantees.

A schema is a type, not a destination. Routing a payload requires all four:

    SchemaCompatible and EdgeDeclared and CapabilityAuthorized and XCFEAdmitted

The first three are reported separately because each can fail alone, and the fourth is never granted
here - `admitted` is false on every result.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import micronaut_registry  # noqa: E402

READ = {"graph.relations.read"}
CANDIDATES = "kuhul://schema/candidates/v1"
PROPOSITION = "kuhul://schema/proposition/v1"
ANSWER = "kuhul://schema/answer/v1"


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = micronaut_registry.load()

    # -- the catalogue ----------------------------------------------------------------------------
    def test_the_registry_loads_and_is_declaration_only(self):
        self.assertTrue(self.registry["ok"], self.registry["problems"])
        self.assertEqual(len(self.registry["list"]), 5)
        self.assertEqual(len(self.registry["edges"]), 6)
        self.assertEqual(self.registry["authority"], "declaration_only")
        for entry in self.registry["list"]:
            self.assertEqual(entry["authority"], "declaration_only")
            self.assertIn(entry["entry"], micronaut_registry.PHASES)

    def test_every_agent_declares_a_contract(self):
        for entry in self.registry["list"]:
            self.assertTrue(entry["input_schema"].startswith("kuhul://schema/"))
            self.assertTrue(entry["output_schema"].startswith("kuhul://schema/"))
            self.assertTrue(entry["capabilities"])
            self.assertTrue(set(entry["operators"]) <= set(micronaut_registry.OPERATORS))

    def test_dependencies_resolve(self):
        for entry in self.registry["list"]:
            for dependency in entry["dependencies"]:
                self.assertIn(dependency, self.registry["by_uri"], (entry["uri"], dependency))

    def test_an_unregistered_dependency_is_refused(self):
        catalogue = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "micronauts.json")
                               .read_text(encoding="utf-8"))
        catalogue["micronauts"][1]["dependencies"] = ["micronaut://v1/nothing"]
        folder = Path(tempfile.mkdtemp())
        path = folder / "micronauts.json"
        path.write_text(json.dumps(catalogue), encoding="utf-8")
        report = micronaut_registry.load(path, ROOT / "kuhul-phase-engine-v0.1.0" / "data"
                                        / "micronaut-edges.json")
        self.assertFalse(report["ok"])
        self.assertIn("dependency", [problem["code"] for problem in report["problems"]])

    # -- typed edges -------------------------------------------------------------------------------
    def test_an_edge_must_match_both_endpoints(self):
        folder = Path(tempfile.mkdtemp())
        wiring = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "micronaut-edges.json")
                            .read_text(encoding="utf-8"))
        wiring["edges"][0]["output_schema_uri"] = ANSWER       # not what aiml produces
        path = folder / "edges.json"
        path.write_text(json.dumps(wiring), encoding="utf-8")
        report = micronaut_registry.load(ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "micronauts.json",
                                        path)
        self.assertFalse(report["ok"])
        self.assertIn("edge_output", [problem["code"] for problem in report["problems"]])

    def test_an_edge_capability_must_be_declared_by_an_endpoint(self):
        folder = Path(tempfile.mkdtemp())
        wiring = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "micronaut-edges.json")
                            .read_text(encoding="utf-8"))
        wiring["edges"][0]["capability"] = "repo.write"
        path = folder / "edges.json"
        path.write_text(json.dumps(wiring), encoding="utf-8")
        report = micronaut_registry.load(ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "micronauts.json",
                                        path)
        self.assertFalse(report["ok"])
        self.assertIn("edge_capability", [problem["code"] for problem in report["problems"]])

    def test_a_reference_edge_is_not_an_execution_grant(self):
        for edge in self.registry["edges"]:
            self.assertEqual(edge["authority"], "declaration_only")

    # -- the three guarantees ----------------------------------------------------------------------
    def test_a_compatible_schema_with_a_declared_edge_and_grant_routes(self):
        result = micronaut_registry.route(self.registry, CANDIDATES,
                                          from_uri="micronaut://v1/aiml", granted=READ)
        self.assertTrue(result["structural"])
        self.assertTrue(result["routing"])
        self.assertTrue(result["authority"])
        self.assertFalse(result["admitted"], "XCFE admission is never granted here")
        self.assertEqual(result["selected"]["target"] in
                         ("micronaut://v1/relations", "micronaut://v1/memory"), True)

    def test_an_undeclared_schema_is_not_structural(self):
        result = micronaut_registry.route(self.registry, "kuhul://schema/unknown/v1", granted=READ)
        self.assertFalse(result["structural"])
        self.assertFalse(result["routing"])
        self.assertEqual(result["refused"], "schema_not_declared")

    def test_a_declared_schema_without_an_edge_is_not_routable(self):
        result = micronaut_registry.route(self.registry, ANSWER, granted=READ)
        self.assertTrue(result["structural"], "answer/v1 is declared as compose's output")
        self.assertFalse(result["routing"])
        self.assertEqual(result["refused"], "no_declared_edge")

    def test_an_unheld_capability_breaks_authority_but_not_routing(self):
        result = micronaut_registry.route(self.registry, CANDIDATES,
                                          from_uri="micronaut://v1/aiml", granted=set())
        self.assertTrue(result["structural"])
        self.assertTrue(result["routing"], "the edge is declared")
        self.assertFalse(result["authority"], "the caller may not use it")
        self.assertEqual(result["refused"], "capability_not_granted")
        self.assertTrue(result["denied"])

    def test_ambiguity_is_reported_and_resolved_deterministically(self):
        first = micronaut_registry.route(self.registry, PROPOSITION,
                                         from_uri="micronaut://v1/relations", granted=READ)
        self.assertTrue(first["ambiguous"], "relations has two declared outgoing edges")
        pairs = [(edge["source"], edge["target"]) for edge in first["candidates"]]
        self.assertEqual(pairs, sorted(pairs))
        second = micronaut_registry.route(self.registry, PROPOSITION,
                                          from_uri="micronaut://v1/relations", granted=READ)
        self.assertEqual(first["selected"], second["selected"])

    def test_the_source_constrains_the_route(self):
        from_relations = micronaut_registry.route(self.registry, PROPOSITION,
                                                  from_uri="micronaut://v1/relations", granted=READ)
        from_aiml = micronaut_registry.route(self.registry, PROPOSITION,
                                             from_uri="micronaut://v1/aiml", granted=READ)
        self.assertTrue(from_relations["routing"])
        self.assertFalse(from_aiml["routing"], "aiml does not produce propositions")

    def test_a_payload_naming_a_target_does_not_create_a_route(self):
        # the model may write {"$schema": ..., "target": "gml://users/42"}: the target is inert.
        result = micronaut_registry.route(self.registry, "gml://users/42", granted=READ)
        self.assertFalse(result["structural"])
        self.assertFalse(result["routing"])
        self.assertEqual(result["refused"], "schema_not_declared")

    def test_the_result_is_deterministic(self):
        first = json.dumps(micronaut_registry.route(self.registry, CANDIDATES, granted=READ),
                           sort_keys=True)
        second = json.dumps(micronaut_registry.route(self.registry, CANDIDATES, granted=READ),
                            sort_keys=True)
        self.assertEqual(first, second)

    def test_the_summary_says_a_declared_edge_is_not_an_admission(self):
        text = micronaut_registry.summary(self.registry)
        self.assertIn("declaration_only", text)
        self.assertIn("not an admission", text)


if __name__ == "__main__":
    unittest.main()
