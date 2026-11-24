"""M44: score model proposals against the existing validators, not against fluency.

The harness is tested with stub completers so the scoring logic is deterministic and needs no server:
a correct plan, a malformed plan, an over-claiming plan, an unparseable reply, and an inconsistent model.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import proposal_eval  # noqa: E402


def plan(*operators, target="graph.matches", authority="proposal"):
    steps = []
    for index, operator in enumerate(operators):
        following = operators[index + 1] if index + 1 < len(operators) else None
        step = {"phase": "Sek", "operator": operator, "target": target, "next": following,
                "authority": authority}
        if operator in ("filter", "map"):
            step["binding"] = "valid"
        steps.append(step)
    return json.dumps(steps)


def reply(text, *, model="stub", tokens=40, latency=100):
    return dict(text=text, model=model, prompt_tokens=80, completion_tokens=tokens,
                latency_ms=latency)


class ScoringTests(unittest.TestCase):
    def test_a_correct_plan_scores_fully(self):
        task = proposal_eval.TASKS[1]      # full_chain: filter -> map -> fold -> reduce
        score = proposal_eval.score_plan(reply(plan("filter", "map", "fold", "reduce")), task)
        self.assertTrue(score["parsed"])
        self.assertEqual(score["valid"], 4)
        self.assertEqual(score["invalid"], 0)
        self.assertTrue(score["order_ok"])
        self.assertTrue(score["binding_ok"])
        self.assertTrue(score["authority_ok"])

    def test_wrong_order_is_measured_not_guessed(self):
        task = proposal_eval.TASKS[1]
        score = proposal_eval.score_plan(reply(plan("map", "filter")), task)
        self.assertFalse(score["order_ok"])
        self.assertEqual(score["operators"], ["map", "filter"])

    def test_an_over_claiming_plan_is_an_authority_violation(self):
        task = proposal_eval.TASKS[0]
        score = proposal_eval.score_plan(reply(plan("filter", "map", authority="execute")), task)
        self.assertFalse(score["authority_ok"])
        self.assertEqual(score["valid"], 0, "the proposals themselves are refused")

    def test_an_unparseable_reply_is_not_zero_quality(self):
        task = proposal_eval.TASKS[0]
        score = proposal_eval.score_plan(reply("Here is my answer: it depends."), task)
        self.assertFalse(score["parsed"])
        self.assertIn("unparseable", score["errors"])
        self.assertEqual(score["valid"], 0)

    def test_json_inside_a_fence_is_recovered(self):
        task = proposal_eval.TASKS[2]
        fenced = "```json\n" + plan("fold", target="proposition.v1") + "\n```"
        score = proposal_eval.score_plan(reply(fenced), task)
        self.assertTrue(score["parsed"], score)
        self.assertTrue(score["order_ok"])

    def test_a_single_object_reply_is_accepted(self):
        task = proposal_eval.TASKS[3]
        single = json.dumps({"phase": "Sek", "operator": "reduce", "target": "graph.matches",
                             "next": None, "authority": "proposal"})
        score = proposal_eval.score_plan(reply(single), task)
        self.assertTrue(score["parsed"])
        self.assertTrue(score["order_ok"])


class EvaluationTests(unittest.TestCase):
    def test_metrics_aggregate_and_left_none_when_unmeasured(self):
        good = plan("filter", "map")
        complete = lambda prompt: reply(good, tokens=None, latency=50)
        report = proposal_eval.evaluate({"stub": complete}, complete_for={"stub": complete}, runs=1)
        model = report["models"]["stub"]
        self.assertEqual(model["parsed"], 4)
        self.assertIsNone(model["completion_tokens"], "tokens are not invented")
        self.assertFalse(model["tokens_measured"])
        self.assertEqual(model["latency_mean_ms"], 50)
        self.assertFalse(report["execution"])
        self.assertEqual(report["authority"], "declaration_only")

    def test_consistency_counts_repeated_plans(self):
        calls = {"n": 0}

        def flaky(prompt):
            calls["n"] += 1
            return reply(plan("filter", "map") if calls["n"] % 2 else plan("map", "filter"))

        report = proposal_eval.evaluate({"flaky": flaky}, complete_for={"flaky": flaky}, runs=2)
        model = report["models"]["flaky"]
        self.assertEqual(model["consistency_measured"], 4)
        self.assertEqual(model["consistent"], 0, "alternating plans are not consistent")

    def test_an_unparseable_model_is_reported_as_such(self):
        bad = lambda prompt: reply("I cannot help with that.")
        report = proposal_eval.evaluate({"bad": bad}, complete_for={"bad": bad}, runs=1)
        model = report["models"]["bad"]
        self.assertEqual(model["parsed"], 0)
        self.assertEqual(model["unparseable"], 4)
        self.assertEqual(model["order_measured"], 0)

    def test_the_summary_states_what_was_measured(self):
        good = lambda prompt: reply(plan("filter", "map"), tokens=None)
        report = proposal_eval.evaluate({"stub": good}, complete_for={"stub": good}, runs=1)
        text = proposal_eval.summarise(report)
        self.assertIn("parsed 4/4", text)
        self.assertIn("not measured", text, "tokens were not reported by the stub")


if __name__ == "__main__":
    unittest.main()
