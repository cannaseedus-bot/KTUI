"""M41: the shared corpus resolver - one knowledge graph, many specialised views.

The review's distinction is the thing under test: **retrieval is not learning**, and **learning is not
training**. Each of those is a separate result shape here, and none of them writes anything.

Also under test: a declared-but-unavailable source (`gramstore://ngrams`) is refused with a reason, and a
`self`-scoped source cannot be read without an identity.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import corpus  # noqa: E402
import user_memory  # noqa: E402

READ = {"graph.relations.read"}


class CorpusManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        user_memory.EVENTS = Path(cls.folder.name) / "user.events.jsonl"
        for predicate, value in (("name", "Bill"), ("status", "active"), ("email", "b@example.com")):
            user_memory.remember(user="42", subject="user", predicate=predicate, value=value)
        cls.manifest = corpus.load()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_the_declaration_is_valid_and_declaration_only(self):
        self.assertTrue(self.manifest["ok"], self.manifest["problems"])
        self.assertEqual(self.manifest["uri"], "corpus://shared/v1")
        self.assertEqual(self.manifest["authority"], "declaration_only")
        self.assertEqual(len(self.manifest["sources"]), 5)
        self.assertEqual(self.manifest["operators"], list(corpus.OPERATORS))

    def test_write_access_cannot_be_implied(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "corpus.json")
                            .read_text(encoding="utf-8"))
        record["access"]["write"] = "allowed"
        path = Path(self.folder.name) / "bad-corpus.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        report = corpus.load(path)
        self.assertFalse(report["ok"])
        self.assertIn("write_access", [problem["code"] for problem in report["problems"]])

    def test_the_training_boundary_must_be_declared(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "corpus.json")
                            .read_text(encoding="utf-8"))
        record["boundaries"]["model_training"] = "same thing as a corpus update"
        path = Path(self.folder.name) / "bad-boundaries.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        report = corpus.load(path)
        self.assertFalse(report["ok"])
        self.assertIn("boundary", [problem["code"] for problem in report["problems"]])

    # -- retrieval ---------------------------------------------------------------------------------
    def test_retrieval_returns_typed_evidence_with_provenance(self):
        result = corpus.retrieve(self.manifest, "gml://relations", caller="42", granted=READ)
        self.assertTrue(result["ok"])
        self.assertEqual(result["scope"], "shared")
        self.assertTrue(result["evidence"])
        for item in result["evidence"]:
            self.assertEqual(item["kind"], "relation")
            self.assertTrue(item["ref"].startswith("gml://relations/"))
            self.assertTrue(item["source"])

    def test_retrieval_never_writes(self):
        result = corpus.retrieve(self.manifest, "gml://relations", caller="42", granted=READ)
        self.assertFalse(result["execution"])
        self.assertFalse(result["mutation"])
        self.assertFalse(result["persistence"])
        self.assertEqual(result["authority"], "declaration_only")

    def test_an_unavailable_source_is_refused_by_the_declaration(self):
        result = corpus.retrieve(self.manifest, "gramstore://ngrams", caller="42", granted=READ)
        self.assertFalse(result["ok"])
        self.assertEqual(result["refused"], "source_unavailable")
        self.assertIn("no GramStore", result["reason"])

    def test_an_undeclared_source_is_refused(self):
        result = corpus.retrieve(self.manifest, "corpus://nope", caller="42", granted=READ)
        self.assertEqual(result["refused"], "source_not_declared")

    def test_a_missing_capability_is_refused(self):
        result = corpus.retrieve(self.manifest, "gml://relations", caller="42", granted=set())
        self.assertEqual(result["refused"], "capability_not_granted")

    def test_a_self_scoped_source_needs_an_identity(self):
        anonymous = corpus.retrieve(self.manifest, "memory://jsonl", caller="", granted=READ)
        self.assertEqual(anonymous["refused"], "scope_required")
        own = corpus.retrieve(self.manifest, "memory://jsonl", caller="42", granted=READ)
        self.assertTrue(own["ok"])
        self.assertEqual(own["scope"], "self")

    def test_the_vectors_source_reads_its_manifest_only(self):
        result = corpus.retrieve(self.manifest, "vectors://embeddinggemma2", caller="42", granted=READ)
        if not (ROOT / "aiml-embeddinggemma2-vectors" / "manifest.json").is_file():
            self.assertEqual(result["refused"], "source_unavailable")
            return
        self.assertTrue(result["ok"])
        value = result["evidence"][0]["value"]
        self.assertEqual(value["dimensions"], 256)
        self.assertEqual(value["rows"], 99524)

    def test_retrieve_all_keeps_the_refusals_alongside(self):
        everything = corpus.retrieve_all(self.manifest, caller="42", granted=READ)
        self.assertIn("gml://relations", everything["readable"])
        self.assertIn("gramstore://ngrams", everything["refused"])
        self.assertFalse(everything["execution"])

    # -- learning versus training ------------------------------------------------------------------
    def test_an_update_is_a_proposal_that_needs_admission(self):
        proposal = corpus.propose_update(self.manifest, source="gml://relations",
                                        proposition={"subject": "user", "predicate": "status"})
        self.assertTrue(proposal["ok"])
        self.assertEqual(proposal["requires"], "xcfe_admitted")
        self.assertFalse(proposal["persisted"])
        self.assertFalse(proposal["admitted"])
        self.assertFalse(proposal["persistence"])

    def test_a_proposal_never_claims_to_train(self):
        proposal = corpus.propose_update(self.manifest, source="aiml://categories",
                                         proposition={"pattern": "WHAT IS *"})
        self.assertIn("never retrains a model", proposal["note"])
        self.assertNotIn("trained", json.dumps(proposal))

    # -- per-micronaut projection -------------------------------------------------------------------
    def test_each_view_is_scoped_by_capability_and_identity(self):
        privileged = corpus.view(self.manifest, caller="42", granted=READ)
        self.assertIn("memory://jsonl", [item["uri"] for item in privileged["readable"]])
        anonymous = corpus.view(self.manifest, caller="", granted=READ)
        self.assertIn("scope_required",
                      [item["refused"] for item in anonymous["refused"]])
        unprivileged = corpus.view(self.manifest, caller="42", granted=set())
        self.assertEqual(unprivileged["readable"], [])
        reasons = {item["refused"] for item in unprivileged["refused"]}
        self.assertIn("capability_not_granted", reasons)
        self.assertTrue(reasons <= {"capability_not_granted", "source_unavailable"}, reasons)

    def test_the_projection_is_deterministic(self):
        first = json.dumps(corpus.view(self.manifest, caller="42", granted=READ), sort_keys=True)
        second = json.dumps(corpus.view(self.manifest, caller="42", granted=READ), sort_keys=True)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
