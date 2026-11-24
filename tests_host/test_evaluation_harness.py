"""M49: the frozen evaluation corpus - reviewed expectations, and a benchmark that cannot be gamed.

Rules under test:

    only frozen cases count        draft and reviewed cases are carried by the corpus but stay out of the
                                   headline number
    nodes are not edges            a plan with valid operators and wrong connections is not a complete plan
    refusal cases need a refusal   an empty plan is not an answer to "commit and push"
    the corpus is offline          nothing in the live path may load the expected answers
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evaluation_harness  # noqa: E402


def perfect(corpus, *, plan_for=None):
    """A model that answers each case with its expectation - the corpus's own self-check."""
    def complete(text):
        for case in corpus["cases"]:
            if case["input"] != text:
                continue
            expect = case["expect"]
            if plan_for:
                return plan_for(case)
            if expect.get("refusal"):
                return dict(text="I cannot do that: the capability is not granted.",
                            model="stub", completion_tokens=10, latency_ms=5)
            operators = [node["operator"] for node in expect["graph"]["nodes"] if not node.get("parent")]
            return dict(text=json.dumps({"phase": expect["phase"], "operators": operators,
                                         "authority": "proposal"}),
                        model="stub", completion_tokens=30, latency_ms=8)
        return dict(text="no plan", model="stub", completion_tokens=3, latency_ms=2)
    return complete


class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = evaluation_harness.load()

    def test_the_corpus_validates(self):
        self.assertTrue(self.corpus["ok"], self.corpus["problems"])
        self.assertEqual(len(self.corpus["cases"]), 12)
        self.assertEqual(len(self.corpus["frozen"]), 8)

    def test_every_case_declares_an_expectation(self):
        for case in self.corpus["cases"]:
            self.assertIn(case["review_status"], ("draft", "reviewed", "frozen"), case["id"])
            self.assertIn(case["expect"]["phase"], ("Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"), case["id"])
            self.assertIsInstance(case["expect"]["graph"]["nodes"], list, case["id"])
            self.assertIsInstance(case["expect"]["graph"]["edges"], list, case["id"])

    def test_the_manifest_counts_match_the_file(self):
        manifest = self.corpus["manifest"]
        self.assertEqual(manifest["cases"], len(self.corpus["cases"]))
        self.assertEqual(manifest["frozen"], len(self.corpus["frozen"]))
        self.assertEqual(manifest["frozen_ids"], [case["id"] for case in self.corpus["frozen"]])

    def test_the_corpus_is_offline(self):
        report = evaluation_harness.isolation()
        self.assertTrue(report["ok"], report["offenders"])

    def test_a_tampered_manifest_is_refused(self):
        import shutil
        import tempfile

        folder = Path(tempfile.mkdtemp()) / "evaluation"
        shutil.copytree(ROOT / "evaluation", folder)
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        manifest["frozen_ids"] = manifest["frozen_ids"][:-1]
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        report = evaluation_harness.load(folder)
        self.assertFalse(report["ok"])
        self.assertIn("frozen_ids", [problem["code"] for problem in report["problems"]])


class ScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = evaluation_harness.load()

    def test_a_perfect_model_completes_every_frozen_case(self):
        result = evaluation_harness.evaluate("perfect", perfect(self.corpus), self.corpus)
        self.assertEqual(result["complete"], len(self.corpus["frozen"]))
        self.assertEqual(result["refusals"]["correct"], result["refusals"]["expected"])

    def test_only_frozen_cases_count(self):
        result = evaluation_harness.evaluate("perfect", perfect(self.corpus), self.corpus)
        self.assertEqual(result["cases"], 8)
        for score in result["scores"]:
            self.assertEqual(score["review"], "frozen")

    def test_valid_operators_with_wrong_edges_are_not_complete(self):
        def reversed_plan(case):
            operators = [node["operator"] for node in case["expect"]["graph"]["nodes"]
                         if not node.get("parent")]
            return dict(text=json.dumps({"phase": case["expect"]["phase"],
                                         "operators": list(reversed(operators)),
                                         "authority": "proposal"}),
                        model="wrong", completion_tokens=20, latency_ms=5)

        result = evaluation_harness.evaluate("wrong", perfect(self.corpus, plan_for=reversed_plan),
                                             self.corpus)
        # A single-operator case is unchanged by reversing, so only multi-operator cases can fail; and a
        # plan is not a refusal, so the refusal cases must fail as well.
        multi = [score for score in result["scores"] if len(score["proposed"] or []) > 1]
        single = [score for score in result["scores"] if score["proposed"] and len(score["proposed"]) == 1]
        refusals = [score for score in result["scores"] if score["expected_refusal"]]
        self.assertTrue(multi, "the corpus should contain a multi-operator case")
        self.assertTrue(all(not score["complete"] for score in multi),
                        [score["case"] for score in multi])
        self.assertTrue(all(score["complete"] for score in single))
        self.assertTrue(all(not score["complete"] for score in refusals))

    def test_an_empty_plan_is_not_a_refusal(self):
        by_input = {case["input"]: case for case in self.corpus["cases"]}

        def empty(text):
            case = by_input[text]
            if case["expect"].get("refusal"):
                return dict(text="", model="quiet", completion_tokens=0, latency_ms=3)
            return perfect(self.corpus)(text)

        result = evaluation_harness.evaluate("quiet", empty, self.corpus)
        self.assertEqual(result["refusals"]["correct"], 0)

    def test_an_extra_operator_fails_the_case(self):
        def over_generating(case):
            operators = [node["operator"] for node in case["expect"]["graph"]["nodes"]
                         if not node.get("parent")]
            if case["category"] == "operator_pair":
                operators = operators + ["reduce"]
            return dict(text=json.dumps({"phase": case["expect"]["phase"], "operators": operators,
                                         "authority": "proposal"}),
                        model="over", completion_tokens=20, latency_ms=5)

        result = evaluation_harness.evaluate("over", perfect(self.corpus, plan_for=over_generating),
                                             self.corpus)
        pairs = [score for score in result["scores"] if score["category"] == "operator_pair"]
        self.assertTrue(pairs)
        for score in pairs:
            self.assertFalse(score["complete"], score["proposed"])
            self.assertEqual(score["verdict"], "extra_operators")

    def test_truncation_is_reported_separately(self):
        def truncated(case):
            return dict(text='{"phase": "Sek", "operators": ["filter"', model="cut",
                        completion_tokens=900, latency_ms=30000, finish_reason="length")

        result = evaluation_harness.evaluate("cut", truncated, self.corpus)
        self.assertEqual(result["parsed"], 0)
        self.assertEqual(result["truncation"], result["cases"])

    def test_results_are_written_as_artifacts(self):
        import tempfile

        result = evaluation_harness.evaluate("perfect", perfect(self.corpus), self.corpus)
        result["started_at"] = "test-run"
        folder = Path(tempfile.mkdtemp())
        path = evaluation_harness.write_result(result, folder)
        self.assertTrue(path.is_file())
        written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(written["complete"], result["complete"])

    def test_the_summary_states_the_separation(self):
        text = evaluation_harness.summary(evaluation_harness.evaluate(
            "perfect", perfect(self.corpus), self.corpus))
        self.assertIn("complete plans", text)
        self.assertIn("nodes", text)
        self.assertIn("refusals", text)


if __name__ == "__main__":
    unittest.main()
