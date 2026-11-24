"""M76: three metrics, four conditions, and the attribution that keeps them honest.

    A    original profile, no binding        graph 1/2 · model-bound 1 · runtime-bound 0
    C    examples profile, no binding        graph 2/2 · model-bound 0 · runtime-bound 0
    E    original profile, Wo binding        graph 2/2 · model-bound 1 · runtime-bound 1
    CE   examples profile, Wo binding        graph 2/2 · model-bound 0 · runtime-bound 2

The point of the guard set: `runtime_bound_complete` is never credited as model target accuracy, and an omitted
target is a model omission even when the host supplies one.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import binding_resolver  # noqa: E402
import bound_scoring  # noqa: E402
import ce_experiment  # noqa: E402
import evaluation_harness  # noqa: E402

CHAIN = ["filter", "map", "fold", "reduce"]


def plan(operators=CHAIN, *, target=None):
    payload = {"phase": "Sek", "operators": list(operators), "authority": "proposal"}
    if target:
        payload["target"] = target
    return dict(text=json.dumps(payload), model="stub", completion_tokens=20, latency_ms=5)


class MetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = evaluation_harness.load()
        cls.registry = binding_resolver.load()
        cls.case = cls.corpus["by_id"]["chain-01"]
        cls.binding = binding_resolver.binding(cls.registry, cls.case["category"])

    def score(self, reply, *, binding=None):
        return bound_scoring.score_bound(self.case, reply, binding if binding is not None else self.binding)

    def test_an_explicit_correct_target_counts_for_the_model_and_the_runtime(self):
        score = self.score(plan(target="graph.matches"))
        self.assertTrue(score["model_graph_exact"])
        self.assertTrue(score["model_bound_complete"])
        self.assertTrue(score["runtime_bound_complete"])
        self.assertEqual(score["binding_source"], "model")

    def test_an_omitted_target_is_a_model_failure_and_a_runtime_success(self):
        score = self.score(plan())
        self.assertTrue(score["model_graph_exact"], "the structure is right")
        self.assertFalse(score["model_bound_complete"], "the model never named a target")
        self.assertTrue(score["runtime_bound_complete"], "the host assembled a valid plan")
        self.assertEqual(score["binding_source"], "wo_resolved")
        self.assertEqual(score["target_state"], "missing")

    def test_a_wrong_target_fails_both(self):
        score = self.score(plan(target="gml://relations"))
        self.assertFalse(score["model_bound_complete"])
        self.assertFalse(score["runtime_bound_complete"],
                         "a conflict is rejected, not resolved into a pass")
        self.assertTrue(score["conflict"])

    def test_without_a_host_binding_the_model_is_the_only_source(self):
        score = self.score(plan(target="graph.matches"), binding=False)
        self.assertEqual(score["binding_source"], "model")
        self.assertTrue(score["model_bound_complete"])
        # the composed plan is valid either way; *who* supplied the binding is the separate question,
        # carried by binding_source and counted as wo_resolved vs model_target
        self.assertTrue(score["runtime_bound_complete"])

    def test_a_missing_target_without_a_binding_is_attributed_to_the_model(self):
        score = self.score(plan(), binding=False)
        self.assertEqual(score["binding_source"], "missing")
        self.assertFalse(score["model_bound_complete"])

    def test_a_wrong_graph_is_neither_kind_of_complete(self):
        score = self.score(plan(["filter", "map"], target="graph.matches"))
        self.assertFalse(score["model_graph_exact"])
        self.assertFalse(score["model_bound_complete"])
        self.assertFalse(score["runtime_bound_complete"])


class SummaryTests(unittest.TestCase):
    def test_the_counts_keep_the_three_metrics_apart(self):
        corpus = evaluation_harness.load()
        case = corpus["by_id"]["chain-01"]
        binding = binding_resolver.binding(binding_resolver.load(), case["category"])
        scores = [bound_scoring.score_bound(case, plan(target="graph.matches"), binding),
                  bound_scoring.score_bound(case, plan(), binding),
                  bound_scoring.score_bound(case, plan(target="gml://relations"), binding)]
        summary = bound_scoring.summarise(scores)
        self.assertEqual(summary["model_graph_exact"], 3)
        self.assertEqual(summary["model_bound_complete"], 1)
        self.assertEqual(summary["runtime_bound_complete"], 2)
        bucket = summary["cases"]["chain-01"]
        self.assertEqual(bucket["wo_resolved"], 1)
        self.assertEqual(bucket["conflicts"], 1)


class ExperimentTests(unittest.TestCase):
    def test_the_four_conditions_are_declared(self):
        self.assertEqual(sorted(ce_experiment.CONDITIONS), ["A", "C", "CE", "E"])
        self.assertFalse(ce_experiment.CONDITIONS["C"]["binding"])
        self.assertTrue(ce_experiment.CONDITIONS["CE"]["binding"])
        self.assertEqual(ce_experiment.CONDITIONS["CE"]["profile"], "C_contract_examples")

    def test_a_run_records_every_condition(self):
        replies = iter([plan(target="graph.matches")] * 20)
        report = ce_experiment.run(evaluation_harness.load(),
                                   complete_for=lambda conversation: next(replies), repeats=1)
        self.assertEqual(sorted(report["results"]), ["A", "C", "CE", "E"])
        for block in report["results"].values():
            self.assertEqual(len(block["scores"]), len(ce_experiment.CASES))

    def test_offline_re_derivation_matches_a_fresh_score(self):
        replies = iter([plan()] * 20)
        report = ce_experiment.run(evaluation_harness.load(),
                                   complete_for=lambda conversation: next(replies), repeats=1)
        rebuilt = bound_scoring.rescore_report(report, evaluation_harness.load())
        before = report["results"]["CE"]["summary"]["runtime_bound_complete"]
        after = rebuilt["results"]["CE"]["summary"]["runtime_bound_complete"]
        self.assertEqual(before, after, "the stored replies already produce these metrics")
        self.assertTrue(rebuilt["rescored"])

    def test_the_report_does_not_claim_validation(self):
        replies = iter([plan()] * 20)
        report = ce_experiment.run(evaluation_harness.load(),
                                   complete_for=lambda conversation: next(replies), repeats=1)
        self.assertIn("never credited", report["note"])
        self.assertFalse(report["execution"])
        self.assertEqual(report["authority"], "declaration_only")


if __name__ == "__main__":
    unittest.main()
