"""M46: composition as a graph - the host resolves edges, and never repairs a plan.

The measured failure was a plan with valid operators and broken connections, so the scoring separates
nodes from edges, and a nested `accumulate` is attached to `fold` rather than accepted as a substitute
for it. Nothing is trimmed, padded or reordered to make a plan pass.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plan_graph  # noqa: E402

FULL = ["filter", "map", "fold", "reduce"]
PAIR = ["filter", "map"]


def plan(operators, *, authority="proposal", phase="Sek"):
    return dict(phase=phase, operators=list(operators), authority=authority)


class GraphTests(unittest.TestCase):
    def test_the_canonical_graph_nests_accumulate_under_fold(self):
        graph = plan_graph.canonical_graph()
        ids = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual([node["operator"] for node in graph["nodes"]],
                         ["filter", "map", "fold", "reduce", "accumulate"])
        self.assertEqual(ids["accumulate#0"]["parent"], "fold#0")
        self.assertIn(["fold#0", "accumulate#0"], graph["edges"])
        self.assertIn(["filter#0", "map#0"], graph["edges"])

    def test_an_exact_chain_scores_exact(self):
        result = plan_graph.compare(plan(FULL))
        self.assertEqual(result["verdict"], "exact")
        self.assertTrue(result["nodes_ok"] and result["edges_ok"])
        self.assertTrue(result["authority_ok"])

    def test_a_nested_accumulate_is_the_same_plan(self):
        result = plan_graph.compare(plan(["filter", "map", "fold", "accumulate", "reduce"]))
        self.assertEqual(result["verdict"], "exact",
                         "the host canonicalises representation, so this is the same graph")
        self.assertEqual(result["proposed_nested"], ["accumulate"])

    def test_a_standalone_accumulate_is_not_a_fold(self):
        result = plan_graph.compare(plan(["filter", "map", "accumulate", "reduce"]))
        self.assertEqual(result["verdict"], "misplaced_accumulate")
        self.assertEqual(result["misplaced_accumulate"], ["accumulate"])
        self.assertNotIn("accumulate", result["canonical"]["operators"])

    def test_extra_operators_are_reported_not_trimmed(self):
        # the measured 1B failure: four operations where two were asked for
        result = plan_graph.compare(plan(["filter", "map", "reduce", "filter"]), expected=PAIR)
        self.assertEqual(result["verdict"], "extra_operators")
        self.assertEqual(result["extra_operators"], ["filter", "reduce"])
        self.assertEqual(result["proposed"], ["filter", "map", "reduce", "filter"],
                         "the proposal is preserved exactly as offered")

    def test_a_short_plan_is_missing_not_padded(self):
        result = plan_graph.compare(plan(PAIR), expected=FULL)
        self.assertEqual(result["verdict"], "missing_operators")
        self.assertEqual(result["missing_operators"], ["fold", "reduce"])
        self.assertEqual(result["proposed"], PAIR)

    def test_wrong_order_is_its_own_failure(self):
        result = plan_graph.compare(plan(["map", "filter", "fold", "reduce"]))
        self.assertEqual(result["verdict"], "wrong_order")
        self.assertTrue(result["nodes_ok"], "the same operators, connected differently")
        self.assertFalse(result["edges_ok"])

    def test_authority_is_scored_separately_from_the_plan(self):
        result = plan_graph.compare(plan(FULL, authority="execute"))
        self.assertTrue(result["nodes_ok"] and result["edges_ok"])
        self.assertFalse(result["authority_ok"])
        self.assertIn("authority", [problem["code"] for problem in result["problems"]])

    def test_an_unregistered_operator_is_not_silently_dropped(self):
        result = plan_graph.compare(plan(["filter", "explode", "map"]))
        self.assertIn("operator", [problem["code"] for problem in result["problems"]])

    def test_an_unknown_phase_is_refused(self):
        result = plan_graph.compare(plan(FULL, phase="Zap"))
        self.assertIn("phase", [problem["code"] for problem in result["problems"]])

    def test_scoring_is_deterministic(self):
        first = json.dumps(plan_graph.compare(plan(FULL)), sort_keys=True)
        second = json.dumps(plan_graph.compare(plan(FULL)), sort_keys=True)
        self.assertEqual(first, second)


class ParseTests(unittest.TestCase):
    def test_a_sequence_object_is_accepted(self):
        parsed = plan_graph.parse_sequence(json.dumps(plan(FULL)))
        self.assertEqual(parsed["operators"], FULL)

    def test_a_bare_list_is_accepted_as_sek(self):
        parsed = plan_graph.parse_sequence(json.dumps(FULL))
        self.assertEqual(parsed["phase"], "Sek")
        self.assertEqual(parsed["operators"], FULL)

    def test_a_fenced_reply_is_recovered(self):
        parsed = plan_graph.parse_sequence("```json\n" + json.dumps(plan(PAIR)) + "\n```")
        self.assertEqual(parsed["operators"], PAIR)

    def test_prose_is_not_a_plan(self):
        self.assertIsNone(plan_graph.parse_sequence("I would filter and then map the candidates."))


class EvaluatorTests(unittest.TestCase):
    def test_the_evaluator_scores_sequence_form_plans(self):
        import proposal_eval

        reply = dict(text=json.dumps(plan(FULL)), model="stub", completion_tokens=90,
                     reasoning_tokens=40, latency_ms=500)
        score = proposal_eval.score_plan(reply, proposal_eval.TASKS[1])
        self.assertEqual(score["form"], "sequence")
        self.assertEqual(score["verdict"], "exact")
        self.assertEqual(score["tokens"]["final_json"], 50,
                         "reasoning tokens are subtracted so the split is honest")

    def test_truncation_is_reported_as_truncation(self):
        import proposal_eval

        reply = dict(text='{"phase": "Sek", "operators": ["filter", "map"', model="stub",
                     completion_tokens=900, latency_ms=1000, finish_reason="length")
        score = proposal_eval.score_plan(reply, proposal_eval.TASKS[1])
        self.assertFalse(score["parsed"])
        self.assertIn("truncated", score["errors"])


if __name__ == "__main__":
    unittest.main()
