"""M16: tool calls really run, and the fast path never invents a result.

Two failures motivated this guard:

* `search the web for news on Nvidia` used to print "🌐 Result for news on nvidia" - a fabricated
  result for a tool that does not exist. A fake result is worse than a refusal: it looks like work.
* `what is the diff` returned "'NoneType' object has no attribute 'strip'" whenever the diff held a
  byte outside cp1252 (an em-dash, a box-drawing character). The subprocess now decodes as utf-8.

The tool verbs themselves are asserted to work, because "make sure the tool calls still work" is the
question this file exists to answer.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402


class M16ToolCallsAndFastPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = chat_app.ChatApp()

    # -- the tool verbs -------------------------------------------------------------------------
    def _assert_real_output(self, out: str, verb: str, argument: str) -> None:
        """A tool answered if it returned git/local output, not a quoted exception.

        Substring checks are useless here: a `git diff` legitimately contains the source of this very
        test, including the words we are looking for. The shape is what distinguishes an answer from
        a swallowed exception - a quoted "<Type>Error: ..." or a bare "'NoneType'".
        """
        self.assertIsInstance(out, str)
        self.assertTrue(out.strip(), f"{verb} {argument} produced nothing")
        self.assertIsNone(re.match(r"^\'?[\w.]+(?:Error|Exception)\':", out.strip()),
                          f"{verb} {argument} returned an exception: {out[:120]}")
        self.assertFalse(out.strip().startswith("'NoneType'"), out[:120])

    def test_git_verbs_answer(self):
        for verb, argument in (("git", "status"), ("git", "diff"), ("git", "log --oneline -3"),
                               ("git", "branch")):
            self._assert_real_output(self.app.run_tool_verb(verb, argument), verb, argument)

    def test_diff_survives_non_cp1252_content(self):
        """The regression: a diff holding an em-dash failed decoding and surfaced as an AttributeError."""
        out = self.app.run_tool_verb("git", "diff")
        self._assert_real_output(out, "git", "diff")
        self.assertTrue(out.startswith(("diff --git", "(no output")), out[:80])

    def test_local_verbs_answer(self):
        self.assertIn(":", self.app.run_tool_verb("time", ""))          # "It's 6:25 PM."
        self.assertIn("77", self.app.run_tool_verb("convert", "25 C F"))
        self.assertTrue(self.app.run_tool_verb("files", "").strip())

    def test_forbidden_verbs_are_still_refused(self):
        for verb, argument in (("rm", "-rf /"), ("git", "push")):
            with self.assertRaises(Exception):
                self.app.run_tool_verb(verb, argument)

    # -- the fast path --------------------------------------------------------------------------
    def test_web_request_is_explained_not_faked(self):
        outcome = chat_app.fast_path_outcome("search the web for news on nvidia")
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome["action"], "explain_no_web")
        self.assertEqual(outcome["argument"], "news on nvidia")
        self.assertNotIn("Result for", outcome["note"])
        self.assertIn("cannot search", outcome["note"])

    def test_math_is_computed_for_real(self):
        for expression, expected in (("25*4", "100"), ("2**10", "1024"), ("(3+4)*2", "14")):
            self.assertEqual(chat_app.safe_math(expression), expected)
        outcome = chat_app.fast_path_outcome("calculate 25*4")
        self.assertEqual(outcome["action"], "math")
        self.assertEqual(outcome["result"], "100")

    def test_non_arithmetic_is_not_forced_through_a_calculator(self):
        self.assertIsNone(chat_app.safe_math("the meaning of life"))
        self.assertIsNone(chat_app.safe_math("__import__('os').getcwd()"))
        self.assertIsNone(chat_app.safe_math("9/0"))
        self.assertEqual(chat_app.fast_path_outcome("calculate the meaning of life")["action"], "defer")

    def test_no_fabricated_results_remain_in_the_source(self):
        source = (ROOT / "chat_app.py").read_text(encoding="utf-8")
        for fake in ('Result for {arg}', '"🌐 Result', '"🧮 Result', "[Local Execution]"):
            self.assertNotIn(fake, source, f"fabricated output is back: {fake}")


if __name__ == "__main__":
    unittest.main()
