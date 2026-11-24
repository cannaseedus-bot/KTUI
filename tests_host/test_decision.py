"""M39: decision closure under unknown probabilities.

The review's two invariants, held as tests:

    UNKNOWN(P(b)) != 0.5        an unresolved probability is never replaced by a prior
    Xul(Action) !=> Xul(Fact)   selecting an action does not close the uncertainty it was decided under
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import decision  # noqa: E402

QUERY = [dict(action="query", branch="improves", utility=8, probability=None),
         dict(action="query", branch="nothing", utility=-2, probability=None),
         dict(action="skip", branch="no_query", utility=0, probability=1.0)]
KNOWN = [dict(action="query", branch="improves", utility=8, probability=0.3),
         dict(action="query", branch="nothing", utility=-2, probability=0.7),
         dict(action="skip", branch="no_query", utility=0, probability=1.0)]


class UnknownProbabilityTests(unittest.TestCase):
    def test_an_unknown_probability_is_never_fifty_percent(self):
        result = decision.decide("q", QUERY, policy="expected_utility")
        self.assertIsNone(result["expected_utility"])
        self.assertIsNone(result["selected_action"])
        self.assertFalse(result["action_collapsed"])
        self.assertEqual(result["refused"], "probabilities_unknown")
        self.assertEqual(result["unresolved_actions"], ["query"])
        # and no substituted prior appears anywhere in the result
        self.assertNotIn(0.5, [value for value in result["expected_utilities"].values()
                               if value is not None])

    def test_probability_types_are_explicit(self):
        self.assertEqual(decision.probability_type(None), "unknown")
        self.assertEqual(decision.probability_type("UNKNOWN"), "unknown")
        self.assertEqual(decision.probability_type("0.4"), "known")
        self.assertEqual(decision.probability_type(0.0), "known")
        self.assertEqual(decision.probability_type(1.0), "known")
        self.assertEqual(decision.probability_type(1.5), "invalid")


class PolicyTests(unittest.TestCase):
    def test_expected_utility_is_computed_when_probabilities_are_known(self):
        result = decision.decide("q", KNOWN, policy="expected_utility")
        self.assertEqual(result["selected_action"], "query")
        self.assertAlmostEqual(result["expected_utility"], 0.3 * 8 + 0.7 * -2, places=6)
        self.assertTrue(result["action_collapsed"])
        self.assertFalse(result["fact_collapsed"])

    def test_minimax_decides_under_unknown_probabilities(self):
        result = decision.decide("query_additional_source", QUERY, policy="minimax")
        self.assertEqual(result["selected_action"], "skip",
                         "worst case -2 for query, 0 for skip")
        self.assertEqual(result["worst_case"], {"query": -2.0, "skip": 0.0})
        self.assertEqual(result["expected_utility"], 0.0, "skip's own probability is known")
        self.assertTrue(result["action_collapsed"])

    def test_expected_utility_does_not_silently_fall_back_to_minimax(self):
        refused = decision.decide("q", QUERY, policy="expected_utility")
        self.assertIsNone(refused["selected_action"])
        chosen = decision.decide("q", QUERY, policy="minimax")
        self.assertEqual(chosen["selected_action"], "skip")
        self.assertNotEqual(refused["policy"], chosen["policy"],
                            "a refused policy is not quietly replaced by another")

    def test_ties_are_deterministic_and_reported(self):
        tied = [dict(action="b", branch="x", utility=1, probability=1.0),
                dict(action="a", branch="y", utility=1, probability=1.0)]
        result = decision.decide("tied", tied, policy="minimax")
        self.assertEqual(result["selected_action"], "a", "ties break by name, not by insertion order")
        self.assertEqual(result["ties"], ["a", "b"])
        again = decision.decide("tied", list(reversed(tied)), policy="minimax")
        self.assertEqual(again["selected_action"], "a")

    def test_invalid_probabilities_are_refused(self):
        broken = [dict(action="query", branch="x", utility=1, probability=1.4)]
        with self.assertRaises(decision.DecisionError):
            decision.decide("q", broken, policy="expected_utility")

    def test_probabilities_must_sum_to_one_when_fully_known(self):
        short = [dict(action="query", branch="a", utility=1, probability=0.2),
                 dict(action="query", branch="b", utility=2, probability=0.2)]
        with self.assertRaisesRegex(decision.DecisionError, "sum to"):
            decision.decide("q", short, policy="expected_utility")

    def test_a_utility_must_be_a_finite_number(self):
        for bad in ("8", None, float("inf"), True):
            with self.assertRaises(decision.DecisionError):
                decision.decide("q", [dict(action="a", branch="x", utility=bad,
                                           probability=1.0)], policy="minimax")

    def test_an_unknown_policy_is_refused(self):
        with self.assertRaisesRegex(decision.DecisionError, "unknown policy"):
            decision.decide("q", KNOWN, policy="prospect")


class ClosureTests(unittest.TestCase):
    def test_closing_an_action_does_not_close_the_fact(self):
        result = decision.decide("q", QUERY, policy="minimax")
        closed = decision.close_action(result)
        self.assertTrue(closed["action_collapsed"])
        self.assertFalse(closed["fact_collapsed"])
        self.assertEqual(closed["closure"], "action")
        self.assertFalse(closed["execution"])

    def test_a_fact_closes_only_on_its_own_verdict(self):
        result = decision.decide("q", QUERY, policy="minimax")
        for verdict in ("UNKNOWN", "", "maybe"):
            with self.assertRaisesRegex(decision.DecisionError, "PASS or FAIL"):
                decision.close_fact(result, verdict=verdict)
        closed = decision.close_fact(result, verdict="FAIL", evidence="no source establishes the cause")
        self.assertTrue(closed["fact_collapsed"])
        self.assertEqual(closed["fact_verdict"], "FAIL")

    def test_an_unselected_decision_cannot_be_closed_as_an_action(self):
        refused = decision.decide("q", QUERY, policy="expected_utility")
        with self.assertRaisesRegex(decision.DecisionError, "no action was selected"):
            decision.close_action(refused)

    def test_the_decision_is_a_proposal_and_never_executes(self):
        result = decision.decide("q", QUERY, policy="minimax")
        self.assertEqual(result["authority"], "proposal")
        self.assertFalse(result["execution"])
        self.assertFalse(result["mutation"])
        self.assertIn("fact_collapsed", result)
        self.assertIn("nothing was executed", result["note"])

    def test_the_summary_states_the_separation(self):
        text = decision.summary(decision.decide("q", QUERY, policy="minimax"))
        self.assertIn("action_collapsed: True", text)
        self.assertIn("fact_collapsed: False", text)
        self.assertIn("execution: False", text)


if __name__ == "__main__":
    unittest.main()
