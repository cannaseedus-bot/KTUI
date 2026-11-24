"""M71: the review packet and the three counts, so an independent review has something to sign.

The packet is what a reviewer needs and nothing more: five frozen expectations, the contract, the authorized
targets, a digest and an unsigned template. It contains **no model output and no score**, because a reviewer
who saw the answer would be grading agreement rather than the expectation.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evaluation_harness  # noqa: E402
import review_attestations  # noqa: E402
import review_packet  # noqa: E402


class StatusTests(unittest.TestCase):
    """Three counts that must never collapse into one another."""

    def test_the_three_counts_are_separate(self):
        status = review_attestations.status(evaluation_harness.load())
        self.assertEqual(status["counts"]["verified"], 3)
        self.assertEqual(status["counts"]["independently_approved"], 0)
        self.assertEqual(status["counts"]["benchmark_eligible"], 0)
        self.assertEqual(status["frozen_cases"], 16)

    def test_the_statement_says_regression_not_validation(self):
        status = review_attestations.status(evaluation_harness.load())
        self.assertIn("regression evidence", status["statement"])
        self.assertIn("not validated accuracy", status["statement"])

    def test_an_unavailable_registry_is_reported_as_such(self):
        status = review_attestations.status(
            evaluation_harness.load(),
            registry_record=review_attestations.registry(Path(tempfile.mkdtemp()) / "absent.json"))
        self.assertFalse(status["registry_available"])
        self.assertEqual(status["counts"]["independently_approved"], 0)
        self.assertIn("reviewer_registry_unavailable", status["verdicts"][0]["reasons"])

    def test_no_verdict_ever_claims_eligibility_without_an_attestation(self):
        status = review_attestations.status(evaluation_harness.load())
        for verdict in status["verdicts"]:
            if not verdict["independent"]:
                self.assertNotIn(verdict["case_id"], status["benchmark_eligible_cases"])


class PacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = evaluation_harness.load()
        cls.packet = review_packet.build()

    def test_the_packet_covers_the_five_chosen_categories(self):
        self.assertEqual([case["case_id"] for case in self.packet["cases"]],
                         ["pair-01", "chain-01", "authority-01", "srai-01", "rest-01"])
        self.assertEqual(self.packet["missing"], [])
        categories = {case["category"] for case in self.packet["cases"]}
        self.assertEqual(len(categories), 5, categories)

    def test_every_case_carries_its_expectation_digest_and_contract(self):
        for case in self.packet["cases"]:
            source = self.corpus["by_id"][case["case_id"]]
            self.assertEqual(case["expected_graph_sha256"], source["expected_graph_sha256"])
            self.assertEqual(case["contract"], source["contract"])
            self.assertEqual(case["expected_graph"], source["expect"]["graph"])

    def test_the_packet_contains_no_model_output_or_score(self):
        # check the record shapes, not a substring scan: the instructions legitimately *mention* a score
        # in order to forbid it.
        def keys(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    yield key
                    yield from keys(value)
            elif isinstance(node, list):
                for item in node:
                    yield from keys(item)

        forbidden = {"reply", "reply_text", "reply_head", "proposed", "score", "latency_ms", "tokens",
                     "verdict", "complete", "parsed"}
        found = forbidden.intersection(keys(self.packet))
        self.assertEqual(found, set(), f"model-output fields leaked into the packet: {found}")

    def test_the_template_is_unsigned(self):
        for case in self.packet["cases"]:
            template = case["attestation_template"]
            self.assertEqual(template["signature"], "SIGN-WITH-YOUR-OWN-KEY")
            self.assertEqual(template["reviewer"], "REPLACE-WITH-YOUR-REVIEWER-ID")
            self.assertEqual(template["schema"], review_attestations.SCHEMA)

    def test_the_reviewer_is_told_not_to_read_model_output(self):
        instructions = self.packet["reviewer_instructions"]
        self.assertIn("no model output", instructions["do_not_read"].replace("contains none",
                                                                           "no model output"))
        self.assertIn("own Ed25519 key", instructions["sign"])
        self.assertIn("never signs", instructions["submit"])

    def test_registration_and_independence_are_described_as_different_authorities(self):
        register = self.packet["reviewer_instructions"]["register"]
        self.assertIn("recognized signer", register)
        self.assertIn("separate onboarding record", register)
        onboarding = self.packet["onboarding_template"]["onboarding"]
        self.assertEqual(onboarding["authorized_by"], "human://project-owner")
        self.assertIn("did not author", onboarding["declaration"])

    def test_the_packet_carries_no_private_key(self):
        blob = json.dumps(self.packet)
        self.assertNotIn("PRIVATE KEY", blob)
        self.assertNotIn("private", blob.lower())

    def test_writing_the_packet_produces_both_files(self):
        folder = Path(tempfile.mkdtemp())
        written = review_packet.write(self.packet, folder)
        self.assertEqual(len(written), 2)
        packet = json.loads((folder / "packet.json").read_text(encoding="utf-8"))
        self.assertEqual(len(packet["cases"]), 5)
        brief = (folder / "REVIEW.md").read_text(encoding="utf-8")
        self.assertIn("chain-01", brief)
        self.assertIn("How to sign", brief)
        self.assertIn("No model output", brief)

    def test_building_twice_gives_the_same_digests(self):
        again = review_packet.build()
        self.assertEqual([case["expected_graph_sha256"] for case in again["cases"]],
                         [case["expected_graph_sha256"] for case in self.packet["cases"]])


if __name__ == "__main__":
    unittest.main()
