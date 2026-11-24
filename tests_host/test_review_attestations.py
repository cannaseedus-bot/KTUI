"""M61: signed review attestations - a review counts when a key proves it.

The distinction under test:

    a registry field claiming independence   is a claim
    a signature over the exact case content  is evidence the payload was not altered by the claimant

And the limit that keeps it honest: a signature proves key possession, not human independence, so an author
key signing every case still yields **zero** benchmark-eligible cases.
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

HAS_CRYPTO = review_attestations._crypto()


def keypair(folder: Path, name: str = "k.pem") -> dict:
    return review_attestations.generate_keypair(folder / name, overwrite=True)


def attestation(case: dict, reviewer: str, decision: str = "approved") -> dict:
    return dict(schema=review_attestations.SCHEMA, case_id=case["id"],
                expected_graph_sha256=case["expected_graph_sha256"],
                contract=case["contract"], reviewer=reviewer, decision=decision)


@unittest.skipUnless(HAS_CRYPTO, "the cryptography package is required")
class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.keys = Path(self.folder.name)
        self.pair = keypair(self.keys)
        self.corpus = evaluation_harness.load()
        self.case = self.corpus["by_id"]["pair-01"]

    def tearDown(self):
        self.folder.cleanup()

    def registry(self, *, independent: bool = False, reviewer: str = "reviewer://test") -> dict:
        # Independence needs an onboarding decision now, not a flag: the synthetic independent reviewer
        # carries one authorized by someone else.
        entry = dict(role="independent" if independent else "author",
                     public_key=self.pair["public_key"],
                     onboarding=dict(authorized_by="human://project-owner", independent=independent,
                                     authorized_at="2026-11-24"))
        return dict(ok=True, available=True, by_id={reviewer: entry}, problems=[])

    def test_a_signed_attestation_verifies(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"), self.pair["private_path"])
        result = review_attestations.verify(signed, self.pair["public_key"])
        self.assertTrue(result["ok"], result["reason"])

    def test_a_changed_decision_breaks_the_signature(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"), self.pair["private_path"])
        signed["decision"] = "rejected"
        self.assertFalse(review_attestations.verify(signed, self.pair["public_key"])["ok"])

    def test_an_attestation_cannot_be_moved_to_another_case(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"), self.pair["private_path"])
        signed["case_id"] = "chain-01"
        self.assertFalse(review_attestations.verify(signed, self.pair["public_key"])["ok"],
                         "the case id is covered by the signature")

    def test_a_rewritten_expectation_is_caught_by_the_digest(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"), self.pair["private_path"])
        signed["expected_graph_sha256"] = "0" * 64
        self.assertFalse(review_attestations.verify(signed, self.pair["public_key"])["ok"])

    def test_a_forged_signature_is_refused(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"), self.pair["private_path"])
        signed["signature"] = "A" * 64
        self.assertFalse(review_attestations.verify(signed, self.pair["public_key"])["ok"])

    def test_an_unregistered_reviewer_is_refused(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://stranger"),
                                          self.pair["private_path"])
        report = review_attestations.check(dict(by_id={self.case["id"]: self.case}), [signed],
                                           self.registry())
        self.assertEqual(report["verified"], 0)
        self.assertIn("reviewer_not_registered", report["verdicts"][0]["reasons"])

    def test_an_author_signature_verifies_but_is_not_independent(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"), self.pair["private_path"])
        report = review_attestations.check(dict(by_id={self.case["id"]: self.case}), [signed],
                                           self.registry(independent=False))
        self.assertEqual(report["verified"], 1)
        self.assertEqual(report["independent"], 0)
        self.assertEqual(report["independently_reviewed_cases"], [])

    def test_an_independent_reviewer_makes_the_case_attested(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"), self.pair["private_path"])
        report = review_attestations.check(dict(by_id={self.case["id"]: self.case}), [signed],
                                           self.registry(independent=True))
        self.assertEqual(report["independently_reviewed_cases"], [self.case["id"]])

    def test_a_rejection_is_not_an_approval(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://test", "rejected"),
                                          self.pair["private_path"])
        report = review_attestations.check(dict(by_id={self.case["id"]: self.case}), [signed],
                                           self.registry(independent=True))
        self.assertEqual(report["verified"], 0)
        self.assertEqual(report["rejected"], [self.case["id"]])


class CorpusAttestationTests(unittest.TestCase):
    def test_the_shipped_corpus_reports_what_it_can_prove(self):
        corpus = evaluation_harness.load()
        self.assertTrue(corpus["ok"], corpus["problems"])
        self.assertEqual(corpus["verified_attestations"], 3,
                         "three author attestations are signed and verify")
        self.assertEqual(corpus["independently_attested"], [],
                         "an author signature never makes a case benchmark-eligible")
        self.assertEqual(len(corpus["eligible"]), 16,
                         "all sixteen cases stay eligible for regression")

    def test_the_private_key_is_not_in_the_corpus(self):
        keys = sorted((ROOT / "evaluation").glob("*.pem"))
        self.assertEqual(keys, [], "a signing key must never sit beside the cases it signs")
        registry = json.loads((ROOT / "evaluation" / "reviewers.json").read_text(encoding="utf-8"))
        for reviewer, entry in registry["reviewers"].items():
            self.assertNotIn("private", json.dumps(entry).lower(), reviewer)
            self.assertTrue(entry.get("public_key"), reviewer)

    def test_the_attestation_file_is_separate_from_the_cases(self):
        attestations = review_attestations.load()
        self.assertEqual(len(attestations), 3)
        for row in attestations:
            self.assertEqual(row["schema"], review_attestations.SCHEMA)
            self.assertIn(row["decision"], review_attestations.DECISIONS)


class FailureClassTests(unittest.TestCase):
    """Four outcomes that must never be confused: unavailable, unregistered, invalid, verified-not-independent."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.keys = Path(self.folder.name)
        self.pair = keypair(self.keys)
        self.corpus = evaluation_harness.load()
        self.case = self.corpus["by_id"]["pair-01"]

    def tearDown(self):
        self.folder.cleanup()

    def entry(self, **overrides) -> dict:
        base = dict(reviewer="reviewer://test", role="independent",
                    public_key=self.pair["public_key"],
                    onboarding=dict(authorized_by="human://project-owner",
                                    authorized_at="2026-11-24", independent=True,
                                    declaration="reviewed independently"))
        base.update(overrides)
        return dict(ok=True, available=True, by_id={"reviewer://test": base}, problems=[])

    def test_a_missing_registry_is_a_configuration_error(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"),
                                          self.pair["private_path"])
        report = review_attestations.check(dict(by_id={self.case["id"]: self.case}), [signed],
                                           review_attestations.registry(self.keys / "absent.json"))
        verdict = report["verdicts"][0]
        self.assertIn("reviewer_registry_unavailable", verdict["reasons"])
        self.assertNotIn("reviewer_not_registered", verdict["reasons"],
                         "an unreadable registry must not read as a policy decision")

    def test_an_unregistered_reviewer_is_distinct_from_an_unavailable_registry(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"),
                                          self.pair["private_path"])
        report = review_attestations.check(dict(by_id={self.case["id"]: self.case}), [signed],
                                           dict(ok=True, available=True, by_id={}, problems=[]))
        self.assertIn("reviewer_not_registered", report["verdicts"][0]["reasons"])

    def test_a_valid_signature_is_verified_even_without_independence(self):
        registry = self.entry(onboarding=None)
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"),
                                          self.pair["private_path"])
        report = review_attestations.check(dict(by_id={self.case["id"]: self.case}), [signed], registry)
        verdict = report["verdicts"][0]
        self.assertTrue(verdict["ok"], verdict["reasons"])
        self.assertEqual(verdict["status"], "verified_not_independent")
        self.assertEqual(verdict["independence_reason"], "onboarding_missing")
        self.assertEqual(report["independently_reviewed_cases"], [])

    def test_onboarding_makes_it_independent(self):
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"),
                                          self.pair["private_path"])
        report = review_attestations.check(dict(by_id={self.case["id"]: self.case}), [signed],
                                           self.entry())
        self.assertEqual(report["verdicts"][0]["status"], "verified_independent")
        self.assertEqual(report["independently_reviewed_cases"], [self.case["id"]])

    def test_a_reviewer_cannot_onboard_themselves(self):
        registry = self.entry(onboarding=dict(authorized_by="reviewer://test", independent=True))
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"),
                                          self.pair["private_path"])
        report = review_attestations.check(dict(by_id={self.case["id"]: self.case}), [signed], registry)
        self.assertEqual(report["verdicts"][0]["independence_reason"], "self_onboarded")
        self.assertEqual(report["independent"], 0)

    def test_an_onboarding_record_marked_not_independent_stays_unverified_for_the_headline(self):
        registry = self.entry(onboarding=dict(authorized_by="human://owner", independent=False))
        signed = review_attestations.sign(attestation(self.case, "reviewer://test"),
                                          self.pair["private_path"])
        report = review_attestations.check(dict(by_id={self.case["id"]: self.case}), [signed], registry)
        self.assertEqual(report["verdicts"][0]["independence_reason"], "onboarding_not_independent")
        self.assertFalse(report["verdicts"][0]["independent"])

    def test_the_shipped_registry_records_an_onboarding_decision(self):
        registry = review_attestations.registry()
        self.assertTrue(registry["available"])
        entry = registry["by_id"]["agent://session-author"]
        self.assertIn("onboarding", entry)
        self.assertEqual(entry["onboarding"]["authorized_by"], "human://project-owner")
        self.assertFalse(entry["onboarding"]["independent"])


class NoSelfApprovalTests(unittest.TestCase):
    """A key generated inside this project can never make a case independently reviewed."""

    def test_the_registry_holds_only_the_author(self):
        registry = review_attestations.registry()
        self.assertTrue(registry["available"])
        self.assertEqual(list(registry["by_id"]), ["agent://session-author"])
        entry = registry["by_id"]["agent://session-author"]
        self.assertFalse(entry["onboarding"]["independent"])

    def test_the_empty_reviewer_slot_holds_no_key(self):
        import json

        record = json.loads((ROOT / "evaluation" / "reviewers.json").read_text(encoding="utf-8"))
        slot = record["awaiting_external_reviewer"]
        self.assertEqual(slot["status"], "none")
        self.assertNotIn("public_key", json.dumps(slot))
        self.assertIn("cannot stand in", slot["note"])

    def test_no_attestation_names_anyone_but_the_author(self):
        rows = review_attestations.load()
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["reviewer"], "agent://session-author")

    def test_the_corpus_reports_zero_eligible(self):
        corpus = evaluation_harness.load()
        self.assertEqual(corpus["independently_attested"], [])
        self.assertEqual(len(corpus["eligible"]), 16, "regression eligibility is unaffected")
        status = review_attestations.status(corpus)
        self.assertEqual(status["counts"]["benchmark_eligible"], 0)

    def test_a_key_would_not_be_enough_anyway(self):
        # even a valid signature from a new signer fails the independence test without onboarding
        folder = tempfile.TemporaryDirectory()
        pair = keypair(Path(folder.name))
        corpus = evaluation_harness.load()
        case = corpus["by_id"]["pair-01"]
        signed = review_attestations.sign(attestation(case, "reviewer://someone"), pair["private_path"])
        report = review_attestations.check(
            dict(by_id={case["id"]: case}), [signed],
            dict(ok=True, available=True,
                 by_id={"reviewer://someone": dict(role="reviewer",
                                                   public_key=pair["public_key"])},
                 problems=[]))
        self.assertEqual(report["verified"], 1, "the signature is valid")
        self.assertEqual(report["independent"], 0, "a valid signature is not an independent review")
        self.assertEqual(report["verdicts"][0]["independence_reason"], "onboarding_missing")
        folder.cleanup()


if __name__ == "__main__":
    unittest.main()
