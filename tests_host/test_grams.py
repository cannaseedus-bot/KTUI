"""M64: Grams-u - adjacency is extracted, relations are not invented, and a missing encoder is reported.

The three separations under test:

    extraction gives candidate n-grams      5 tokens -> 5 unigrams, 4 bigrams, 3 trigrams
    windowing is a choice, not a default    sliding spans the text; bound keeps five positional slots and
                                            no cross-slot trigram
    relations and vectors are not claimed   `relation` stays None with `requires: "gml"`, and a missing
                                            adapter yields vectors None with a reason
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import grams  # noqa: E402

TEXT = "Bill has a black dog"


class ExtractionTests(unittest.TestCase):
    def test_five_tokens_produce_the_expected_ngrams(self):
        extraction = grams.extract(TEXT)
        self.assertEqual(extraction["by_size"], {"1": 5, "2": 4, "3": 3})
        self.assertEqual([gram["text"] for gram in extraction["grams"] if gram["size"] == 2],
                         ["Bill has", "has a", "a black", "black dog"])
        self.assertEqual([gram["text"] for gram in extraction["grams"] if gram["size"] == 3],
                         ["Bill has a", "has a black", "a black dog"])

    def test_every_gram_carries_provenance(self):
        extraction = grams.extract(TEXT)
        for gram in extraction["grams"]:
            self.assertTrue(gram["id"].startswith("gram://"), gram)
            self.assertIn("#", gram["id"])
            self.assertEqual(gram["tokens"], TEXT.split()[gram["start"]:gram["end"] + 1], gram["id"])

    def test_sliding_and_bound_are_different_graphs(self):
        sliding = grams.extract(TEXT, mode="sliding")
        bound = grams.extract(TEXT, mode="bound", slots=5)
        self.assertEqual(sliding["by_size"], {"1": 5, "2": 4, "3": 3})
        self.assertEqual(bound["by_size"], {"1": 5, "2": 4},
                         "a positional binding declares pairs, not trigrams")
        self.assertEqual(bound["mode"], "bound")

    def test_bound_needs_a_slot_count_that_fits(self):
        with self.assertRaises(grams.GramError):
            grams.extract(TEXT, mode="bound", slots=9)
        with self.assertRaises(grams.GramError):
            grams.extract(TEXT, mode="sideways")

    def test_empty_input_is_empty_not_an_error(self):
        extraction = grams.extract("   ")
        self.assertTrue(extraction["empty"])
        self.assertEqual(extraction["grams"], [])
        self.assertEqual(grams.summary(extraction), "grams · no tokens")

    def test_the_provenance_digest_tracks_the_extraction(self):
        first = grams.provenance(grams.extract(TEXT))
        second = grams.provenance(grams.extract(TEXT))
        self.assertEqual(first["digest"], second["digest"])
        other = grams.provenance(grams.extract("Bill has a black cat"))
        self.assertNotEqual(first["digest"], other["digest"])


class RelationTests(unittest.TestCase):
    def test_adjacency_is_never_a_typed_relation(self):
        candidates = grams.relation_candidates(grams.extract(TEXT))
        self.assertEqual(candidates["count"], 4)
        for candidate in candidates["candidates"]:
            self.assertIsNone(candidate["relation"], "the graph decides, not the extractor")
            self.assertEqual(candidate["requires"], "gml")

    def test_each_bigram_cites_the_trigrams_that_contain_it(self):
        candidates = grams.relation_candidates(grams.extract(TEXT))
        by_text = {candidate["text"]: candidate for candidate in candidates["candidates"]}
        self.assertTrue(by_text["Bill has"]["supported_by"])
        self.assertTrue(by_text["black dog"]["supported_by"])

    def test_a_proposal_is_a_proposal(self):
        proposal = grams.propose(grams.extract(TEXT))
        self.assertEqual(proposal["phase"], "Sek")
        self.assertEqual(proposal["operators"], ["filter", "map", "fold"])
        self.assertEqual(proposal["authority"], "proposal")
        self.assertFalse(proposal["admitted"])
        self.assertFalse(proposal["execution"])


class EncoderTests(unittest.TestCase):
    def test_the_stored_encoder_is_reported_when_present(self):
        status = grams.encoder()
        if not status["available"]:
            self.assertTrue(status["reason"])
            return
        self.assertEqual(status["dimensions"], 256)
        self.assertEqual(status["model"], "google/embeddinggemma-2")

    def test_no_adapter_means_no_scores(self):
        result = grams.embed(grams.extract(TEXT))
        if not grams.encoder()["available"]:
            self.assertFalse(result["available"])
            return
        self.assertFalse(result["available"])
        self.assertIsNone(result["vectors"], "a similarity nobody computed is not zero")
        self.assertIn("no adapter", result["reason"])

    def test_a_failing_adapter_is_reported_not_scored(self):
        class Broken:
            def for_text(self, text, top_k=3):
                raise RuntimeError("the vector lane is unreadable")

        result = grams.embed(grams.extract(TEXT), adapter=Broken())
        self.assertFalse(result["available"])
        self.assertIn("unreadable", result["reason"])

    def test_an_adapter_supplies_scores_and_nothing_else(self):
        class Stub:
            def for_text(self, text, top_k=3):
                return [("a dog", 0.81), ("has", 0.42)]

        result = grams.embed(grams.extract(TEXT), adapter=Stub())
        self.assertTrue(result["available"])
        self.assertEqual(result["grams"], 7,
                         "the four bigrams and three trigrams were scored; unigrams are not pairs")
        for row in result["vectors"]:
            self.assertTrue(row["nearest"])
            self.assertTrue(0.0 <= row["nearest"][0]["score"] <= 1.0)
        self.assertFalse(result["execution"])


if __name__ == "__main__":
    unittest.main()
