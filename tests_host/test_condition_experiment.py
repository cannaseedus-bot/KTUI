"""M51: three instruction conditions against one frozen graph validator.

The experiment exists because two very different models made the *same* structural error, which points at
the instruction rather than at capability. These guards keep the experiment honest:

    the same validator scores every cell          `evaluation_harness.score_case`, the frozen corpus one
    the instruction is the only thing that changes the case text plus a suffix, nothing else
    no metric is invented                          tokens and latency come from the reply, or stay None
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import condition_experiment  # noqa: E402
import evaluation_harness  # noqa: E402

AMBIGUOUS = ["filter", "map", "accumulate", "reduce"]
CONTRACTED = ["filter", "map", "fold", "reduce"]


def reply(operators, *, tokens=40, latency=10):
    return dict(text=json.dumps({"phase": "Sek", "operators": operators, "authority": "proposal"}),
                model="stub", completion_tokens=tokens, latency_ms=latency, finish_reason="stop")


class ConditionTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = evaluation_harness.load()
        cls.prompts = condition_experiment.instructions(cls.corpus)

    def test_the_case_text_is_identical_across_conditions(self):
        case = self.corpus["by_id"][condition_experiment.CASE]["input"]
        for name, prompt in self.prompts.items():
            self.assertTrue(prompt.startswith(case), name)

    def test_the_semantic_condition_states_the_containment_rule(self):
        self.assertIn("FOLD owns ACCUMULATE", self.prompts["B_semantic"])
        self.assertIn("REDUCE follows FOLD", self.prompts["B_semantic"])

    def test_the_structural_condition_states_containment_execution_and_authority(self):
        contract = self.prompts["C_structural"]
        for phrase in ("Containment: FOLD -> ACCUMULATE",
                       "Execution order: FILTER -> MAP -> FOLD -> REDUCE",
                       "Do not replace FOLD with ACCUMULATE",
                       'Authority must be "proposal"'):
            self.assertIn(phrase, contract)

    def test_a_missing_case_is_an_error_not_an_empty_prompt(self):
        with self.assertRaises(KeyError):
            condition_experiment.instructions({"by_id": {}})


class RunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = evaluation_harness.load()

    def run_with(self, responses):
        calls = []

        def complete(prompt):
            calls.append(prompt)
            return responses(prompt)

        report = condition_experiment.run(["stub"], self.corpus, complete_for={"stub": complete})
        return report, calls

    def test_the_baseline_reproduces_the_measured_failure(self):
        report, _ = self.run_with(lambda prompt: reply(AMBIGUOUS))
        baseline = report["results"]["stub"]["A_baseline"]
        self.assertEqual(baseline["verdict"], "misplaced_accumulate")
        self.assertFalse(baseline["complete"])

    def test_a_contract_that_is_followed_scores_exact(self):
        def follow(prompt):
            return reply(CONTRACTED if "Containment" in prompt else AMBIGUOUS)

        report, _ = self.run_with(follow)
        self.assertEqual(report["results"]["stub"]["A_baseline"]["verdict"], "misplaced_accumulate")
        self.assertEqual(report["results"]["stub"]["C_structural"]["verdict"], "exact")
        self.assertTrue(report["results"]["stub"]["C_structural"]["complete"])

    def test_a_model_that_ignores_the_contract_still_fails(self):
        report, _ = self.run_with(lambda prompt: reply(AMBIGUOUS))
        self.assertFalse(report["results"]["stub"]["C_structural"]["complete"],
                         "the contract must not be rewarded for merely being present")

    def test_each_condition_sends_its_own_prompt_once(self):
        _, calls = self.run_with(lambda prompt: reply(CONTRACTED))
        self.assertEqual(len(calls), len(condition_experiment.CONDITIONS))
        self.assertEqual(len(set(calls)), len(calls), "the prompts differ")

    def test_a_failed_call_is_recorded_not_swallowed(self):
        def explode(prompt):
            raise TimeoutError("no answer")

        report, _ = self.run_with(explode)
        for cell in report["results"]["stub"].values():
            self.assertIn("TimeoutError", cell["error"])
            self.assertFalse(cell["complete"])

    def test_unmeasured_values_stay_none(self):
        def quiet(prompt):
            return dict(text=json.dumps({"phase": "Sek", "operators": CONTRACTED,
                                         "authority": "proposal"}),
                        model="quiet", completion_tokens=None, latency_ms=None)

        report, _ = self.run_with(quiet)
        cell = report["results"]["stub"]["C_structural"]
        self.assertIsNone(cell["tokens"])
        self.assertIsNone(cell["latency_ms"])

    def test_the_report_says_what_it_is(self):
        report, _ = self.run_with(lambda prompt: reply(CONTRACTED))
        self.assertEqual(report["case"], condition_experiment.CASE)
        self.assertIn("does not estimate general capability", report["note"])
        self.assertFalse(report["execution"])
        self.assertEqual(report["authority"], "declaration_only")

    def test_the_summary_lists_every_condition(self):
        report, _ = self.run_with(lambda prompt: reply(CONTRACTED))
        text = condition_experiment.summary(report)
        for condition in condition_experiment.CONDITIONS:
            self.assertIn(condition, text)


if __name__ == "__main__":
    unittest.main()
