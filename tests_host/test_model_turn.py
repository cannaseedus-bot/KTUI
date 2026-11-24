"""M89: the model turn as three observable handlers - and finishing a stream is not verification.

process (Sek), validate (Ch'en) and close (Xul) are separate contracts. `verified` means examined, not true. A refused
answer is a legitimate result whose emission still succeeded, so `ok`, `emitted` and `verified` are three fields.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import model_turn  # noqa: E402


class ProcessTests(unittest.TestCase):
    def test_a_completed_stream_is_a_candidate(self):
        result = model_turn.process(text="Rex is your dog.", chunks=4)
        self.assertTrue(result["ok"])
        self.assertEqual(result["transport"], "ok")
        self.assertEqual(result["chars"], len("Rex is your dog."))
        self.assertEqual(result["chunks"], 4)

    def test_a_transport_failure_is_not_a_validation_verdict(self):
        result = model_turn.process(text="", chunks=0, error=TimeoutError("read timed out"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["transport"], "failed")
        self.assertIn("TimeoutError", result["reason"])


class ValidateTests(unittest.TestCase):
    def test_an_ordinary_answer_is_accepted(self):
        result = model_turn.validate("Rex is your dog.")
        self.assertEqual(result["verdict"], "accepted")
        self.assertTrue(result["verified"])
        self.assertTrue(result["ok"])

    def test_a_refusal_is_verified_and_not_a_success(self):
        result = model_turn.validate("I cannot do that: the capability is not granted.")
        self.assertEqual(result["verdict"], "refused")
        self.assertTrue(result["verified"], "a refusal is a real answer")
        self.assertFalse(result["ok"], "the turn did not succeed")

    def test_an_empty_stream_is_not_verified(self):
        result = model_turn.validate("   ")
        self.assertEqual(result["verdict"], "empty")
        self.assertFalse(result["verified"])
        self.assertFalse(result["ok"])

    def test_a_tool_request_is_a_valid_output(self):
        result = model_turn.validate("", tool_calls=True)
        self.assertEqual(result["verdict"], "tool_call")
        self.assertTrue(result["ok"])

    def test_transport_failure_cannot_be_verified(self):
        result = model_turn.validate("partial", error=ConnectionError("reset"))
        self.assertEqual(result["verdict"], "transport_failed")
        self.assertFalse(result["verified"])
        self.assertEqual(result["transport"], "failed")

    def test_refusal_phrasings_are_recognised(self):
        for text in ("I can't help with that.", "I'm sorry, but I won't.",
                     "Sorry, I cannot open that file.", "I am unable to do that."):
            self.assertEqual(model_turn.validate(text)["verdict"], "refused", text)


class CloseTests(unittest.TestCase):
    def test_an_accepted_answer_closes_ok(self):
        result = model_turn.close("accepted", emitted=True)
        self.assertEqual(result["outcome"], "accepted")
        self.assertTrue(result["ok"])
        self.assertTrue(result["emitted"])
        self.assertTrue(result["verified"])

    def test_a_displayed_refusal_closes_with_ok_false(self):
        result = model_turn.close("refused", emitted=True)
        self.assertEqual(result["outcome"], "refused")
        self.assertTrue(result["emitted"], "the refusal was displayed")
        self.assertFalse(result["ok"], "and the turn did not succeed")
        self.assertTrue(result["verified"])

    def test_an_unemitted_answer_is_not_a_success(self):
        result = model_turn.close("accepted", emitted=False)
        self.assertFalse(result["ok"])
        self.assertIn("not displayed", result["reason"])

    def test_a_transport_failure_closes_as_failed(self):
        result = model_turn.close("transport_failed", emitted=True)
        self.assertEqual(result["outcome"], "failed")
        self.assertFalse(result["verified"])

    def test_an_unknown_verdict_is_refused(self):
        result = model_turn.close("probably_fine", emitted=True)
        self.assertEqual(result["outcome"], "failed")
        self.assertNotIn("probably_fine", model_turn.VERDICTS)

    def test_the_three_facts_are_independent(self):
        refused = model_turn.close("refused", emitted=True)
        self.assertEqual((refused["emitted"], refused["verified"], refused["ok"]), (True, True, False))
        failed = model_turn.close("empty", emitted=True)
        self.assertEqual((failed["emitted"], failed["verified"], failed["ok"]), (True, False, False))


if __name__ == "__main__":
    unittest.main()
