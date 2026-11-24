"""M80: the learning chain end to end - candidate, proposal, verdict, evidence record, and nothing more.

The chain was structurally present (delta, verified delta, ledger append) but never exercised in one call. These
guards hold the three boundaries the rest of the system depends on:

    no graph mutation        graph_mutated is false at the record and stays false
    no admission             admitted is false at every hop
    no unverified hop        a FAIL is recorded as FAIL, and a malformed candidate never reaches the ledger
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evidence_record  # noqa: E402
import learning_pipeline  # noqa: E402

CANDIDATE = dict(source="black dog", target="large canine", relation="semantic_similarity",
                 score=0.87)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original = evidence_record.LOG
        evidence_record.LOG = Path(self.folder.name) / "ledger.jsonl"

    def tearDown(self):
        evidence_record.LOG = self.original
        self.folder.cleanup()

    def rows(self):
        return evidence_record.load()

    def test_a_candidate_reaches_an_evidence_record(self):
        result = learning_pipeline.run(CANDIDATE, verdict="PASS", evidence="gml://relations#a")
        self.assertTrue(result["ok"], result.get("refused"))
        hops = [step["hop"] for step in result["steps"]]
        self.assertEqual(hops, ["candidate", "delta", "route", "verified", "ledger"])
        self.assertEqual(len(self.rows()), 1)

    def test_the_record_says_evidence_only(self):
        result = learning_pipeline.run(CANDIDATE, verdict="PASS")
        record = result["evidence"]
        self.assertFalse(record["admitted"])
        self.assertFalse(record["graph_mutated"])
        self.assertEqual(record["persistence"], "evidence_only")
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["verification"]["verdict"], "PASS")

    def test_no_hop_admits_or_mutates(self):
        result = learning_pipeline.run(CANDIDATE, verdict="PASS")
        self.assertFalse(result["admitted"])
        self.assertFalse(result["execution"])
        self.assertFalse(result["mutation"])
        self.assertEqual(result["delta"]["authority"], "proposal")
        self.assertEqual(result["verdict"]["authority"], "verified")

    def test_a_fail_is_recorded_as_a_fail(self):
        result = learning_pipeline.run(CANDIDATE, verdict="FAIL", evidence="no source supports it")
        self.assertTrue(result["ok"])
        self.assertEqual(result["evidence"]["verification"]["verdict"], "FAIL")
        self.assertFalse(result["evidence"]["admitted"])
        self.assertEqual(len(self.rows()), 1)

    def test_a_malformed_candidate_never_reaches_the_ledger(self):
        for bad in (dict(CANDIDATE, score="high"), dict(CANDIDATE, score=True),
                    dict(source="a", target="b", relation="semantic_similarity")):
            result = learning_pipeline.run(bad, verdict="PASS")
            self.assertFalse(result["ok"], bad)
            self.assertEqual(result["refused"], "candidate_invalid")
            self.assertEqual(len(self.rows()), 0, "a refused candidate writes nothing")

    def test_an_invalid_verdict_is_refused(self):
        result = learning_pipeline.run(CANDIDATE, verdict="MAYBE")
        self.assertEqual(result["refused"], "verdict_invalid")
        self.assertEqual(len(self.rows()), 0)

    def test_recording_can_be_skipped_for_a_dry_run(self):
        result = learning_pipeline.run(CANDIDATE, verdict="PASS", record=False)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["evidence"])
        self.assertEqual(len(self.rows()), 0, "a dry run writes nothing")

    def test_the_chain_is_deterministic_apart_from_the_ledger_position(self):
        first = learning_pipeline.run(CANDIDATE, verdict="PASS")
        # the second delivery is explicitly a re-delivery: the same message twice is not two evidences
        second = learning_pipeline.run(CANDIDATE, verdict="PASS", allow_redelivery=True)
        self.assertEqual(first["evidence"]["payload"], second["evidence"]["payload"])
        self.assertEqual(first["evidence"]["message_id"], second["evidence"]["message_id"])
        self.assertNotEqual(first["evidence"]["verification"], None)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original = evidence_record.LOG
        evidence_record.LOG = Path(self.folder.name) / "ledger.jsonl"

    def tearDown(self):
        evidence_record.LOG = self.original
        self.folder.cleanup()

    def test_the_summary_states_the_boundary(self):
        text = learning_pipeline.summary(learning_pipeline.run(CANDIDATE, verdict="PASS"))
        self.assertIn("admitted False", text)
        self.assertIn("evidence_only", text)
        self.assertIn("graph_mutated False", text)

    def test_a_refusal_summary_names_the_hop(self):
        text = learning_pipeline.summary(learning_pipeline.run(dict(CANDIDATE, score="high"),
                                                              verdict="PASS"))
        self.assertIn("REFUSED candidate_invalid", text)
        self.assertIn("1 hop", text)


class DeliveryIntegrityTests(unittest.TestCase):
    """Two narrow failures the review asked for, both about the ledger telling the truth."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original = evidence_record.LOG
        evidence_record.LOG = Path(self.folder.name) / "ledger.jsonl"

    def tearDown(self):
        evidence_record.LOG = self.original
        self.folder.cleanup()

    def rows(self):
        return evidence_record.load()

    def test_a_second_delivery_is_refused_not_counted(self):
        learning_pipeline.run(CANDIDATE, verdict="PASS")
        again = learning_pipeline.run(CANDIDATE, verdict="PASS")
        self.assertFalse(again["ok"])
        self.assertEqual(again["refused"], "duplicate_delivery")
        self.assertEqual(len(self.rows()), 1, "one verified message is one piece of evidence")
        self.assertEqual(again["existing"]["request_id"],
                         f"delta:{CANDIDATE['source']}->{CANDIDATE['target']}:1")

    def test_a_redelivery_is_recorded_as_a_redelivery(self):
        learning_pipeline.run(CANDIDATE, verdict="PASS")
        again = learning_pipeline.run(CANDIDATE, verdict="PASS", allow_redelivery=True)
        self.assertTrue(again["ok"])
        self.assertEqual(again["delivery"], "redelivery")
        self.assertEqual(len(self.rows()), 2)
        ledger_step = [step for step in again["steps"] if step["hop"] == "ledger"][0]
        self.assertEqual(ledger_step["delivery"], "redelivery")
        self.assertIsNotNone(ledger_step["original_sequence"])

    def test_a_persistence_failure_is_reported_as_not_persisted(self):
        original = evidence_record.append

        def broken(*args, **kwargs):
            raise OSError("disk full")

        evidence_record.append = broken
        try:
            result = learning_pipeline.run(CANDIDATE, verdict="PASS")
        finally:
            evidence_record.append = original
        self.assertFalse(result["ok"])
        self.assertEqual(result["refused"], "evidence_not_persisted")
        self.assertFalse(result["persisted"])
        self.assertTrue(result["verification_ok"],
                        "the verification succeeded; the persistence did not")
        self.assertIn("disk full", result["detail"])
        self.assertEqual(len(self.rows()), 0)
        self.assertIn("not written", result["note"])

    def test_a_dry_run_never_touches_the_ledger(self):
        result = learning_pipeline.run(CANDIDATE, verdict="PASS", record=False)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["evidence"])
        self.assertIsNone(result.get("persisted"))
        self.assertEqual(len(self.rows()), 0)


if __name__ == "__main__":
    unittest.main()
