"""M26: retrieval and composition - the two contracts that were declared but never consumed.

The behaviour the review specified: retrieve the relations that answer the question, compose a
paragraph from them under the declared contract, and verify the paragraph against the evidence before
anyone reads it.

  retrieval.gml   weights, threshold, candidate cap   (scoring is ranked, not guessed)
  composition.gml sentence templates, ordering, separators   (the plan is data)

Nothing is invented to fill a slot: an unsupported attribute fails verification and the paragraph is
withheld. A value that changed is history, not a defect, and is reported as a warning.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import compose  # noqa: E402
import phases  # noqa: E402
import user_memory  # noqa: E402

CONTRACTS = phases.ROOT / "aiml_contracts"


class M26RetrievalAndComposition(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.events = Path(self.folder.name) / "user.events.jsonl"
        self.original_events = user_memory.EVENTS
        user_memory.EVENTS = self.events

    def tearDown(self):
        user_memory.EVENTS = self.original_events
        self.folder.cleanup()

    def facts(self, pairs, user="alice"):
        for predicate, value in pairs:
            user_memory.remember(user=user, subject="pet", predicate=predicate, value=value,
                                 path=self.events)

    # -- the contracts ---------------------------------------------------------------------------
    def test_both_contracts_load_from_the_package(self):
        contract = compose.load()
        self.assertTrue(contract["ok"], contract["problems"])
        settings = contract["settings"]
        self.assertEqual(settings["strategy"], "lexical_then_recency")
        self.assertGreater(settings["weight_lexical"], 0)
        self.assertLessEqual(settings["min_score"], 1)
        self.assertEqual(settings["max_sentences"], 2)
        self.assertTrue(settings["sentences"])

    def test_the_composition_contract_is_load_bearing(self):
        folder = Path(self.folder.name) / "contracts"
        shutil.copytree(CONTRACTS, folder)
        text = (folder / "composition.gml").read_text(encoding="utf-8")
        (folder / "composition.gml").write_text(text.replace("max_sentences 2", "max_sentences 1"),
                                                encoding="utf-8")
        self.facts([("personality", "playful"), ("size", "big")])
        short = compose.paragraph("alice", "tell me about my dog", folder=folder)
        self.assertEqual(len(short["plan"]["sentences"]), 1)
        full = compose.paragraph("alice", "tell me about my dog")
        self.assertEqual(len(full["plan"]["sentences"]), 2)

    # -- retrieval -------------------------------------------------------------------------------
    def test_relations_are_ranked_and_filtered_by_the_threshold(self):
        self.facts([("name", "Rex"), ("personality", "playful"), ("colour", "black")])
        settings = compose.load()["settings"]
        kept = compose.retrieve("alice", "tell me about my dog", settings)
        self.assertTrue(kept)
        scores = [row["score"] for row in kept]
        self.assertEqual(scores, sorted(scores, reverse=True), "ranking is deterministic")
        self.assertTrue(all(row["score"] >= settings["min_score"] for row in kept))
        self.assertLessEqual(len(kept), int(settings["max_candidates"]))

    # -- composition ------------------------------------------------------------------------------
    def test_the_paragraph_uses_the_name_as_an_identifier(self):
        self.facts([("name", "Rex"), ("personality", "playful"), ("size", "big")])
        result = compose.paragraph("alice", "tell me about my dog")
        self.assertTrue(result["ok"], result["verification"])
        self.assertIn("pet (Rex)", result["paragraph"])
        self.assertIn("playful", result["paragraph"])
        self.assertIn("and", result["paragraph"], "the conjunction comes from the contract")

    def test_attributes_are_ordered_by_the_contract(self):
        self.facts([("personality", "playful"), ("size", "big"), ("colour", "black")])
        result = compose.paragraph("alice", "tell me about my dog")
        self.assertEqual(result["plan"]["predicates"], ["colour", "personality", "size"])

    # -- verification -----------------------------------------------------------------------------
    def test_unsupported_attributes_fail_and_the_paragraph_is_withheld(self):
        self.facts([("personality", "playful")])
        contract = compose.load()
        kept = compose.retrieve("alice", "tell me about my dog", contract["settings"])
        plan = compose.compose(kept, contract["settings"])
        forged = dict(plan, attributes=plan["attributes"] + ["spotted"])
        report = compose.verify(forged, kept, user="alice")
        self.assertFalse(report["ok"])
        self.assertIn("unsupported_attribute",
                      [problem["code"] for problem in report["problems"]])

    def test_a_superseded_value_is_a_warning_not_a_failure(self):
        self.facts([("name", "Max"), ("name", "Rex"), ("size", "big")])
        result = compose.paragraph("alice", "tell me about my dog")
        self.assertTrue(result["ok"], result["verification"])
        self.assertIn("Rex", result["paragraph"])
        self.assertEqual([warning["code"] for warning in result["verification"]["warnings"]],
                         ["superseded_value"])

    def test_nothing_is_invented_to_fill_the_gap(self):
        self.facts([("personality", "playful"), ("size", "big")])
        result = compose.paragraph("alice", "tell me about my dog")
        known = {row["value"] for row in compose.relations("alice")}
        for attribute in result["plan"]["attributes"]:
            self.assertIn(attribute, known)

    def test_an_empty_memory_produces_no_paragraph(self):
        result = compose.paragraph("alice", "tell me about my dog")
        self.assertFalse(result["ok"])
        self.assertEqual(result["paragraph"], "")
        self.assertIn("no relations", result["plan"]["reason"])

    # -- the host ----------------------------------------------------------------------------------
    def test_the_daemon_answers_a_composition_request(self):
        self.facts([("name", "Rex"), ("personality", "playful"), ("size", "big")])
        app = chat_app.ChatApp()
        app.user_id = "alice"
        kind, body = app.local_answer("tell me about my dog")
        self.assertEqual(kind, "compose")
        self.assertIn("pet (Rex)", body)
        self.assertIn("verification passed", body)

    def test_composing_never_writes(self):
        self.facts([("name", "Rex"), ("size", "big")])
        before = len(user_memory.events("alice"))
        compose.paragraph("alice", "tell me about my dog")
        self.assertEqual(len(user_memory.events("alice")), before)


if __name__ == "__main__":
    unittest.main()
