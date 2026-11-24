"""M33: the five operators, and URI resolution that navigates without granting anything.

Two rules are held here.

**Rank changes only where it is declared.** FILTER and MAP preserve rank (same shape, fewer or
transformed items), FOLD and its inner ACCUMULATE preserve the accumulator's rank, and REDUCE collapses
along a declared axis. The provenance of every stage records which happened.

**A URI that resolves grants nothing.** Each envelope says `authority: declaration_only` and
`execution: false`; unknown schemes, missing resources, cycles and budget overruns are refused with a
reason rather than a traceback.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import operators  # noqa: E402


def candidates():
    return [dict(row=1, pattern="WHAT IS AI", score=1.0, compatible=True),
            dict(row=88107, pattern="WHAT IS A AI", score=0.995, compatible=False),
            dict(row=88466, pattern="WHAT IS AN AI", score=0.994, compatible=False),
            dict(row=93242, pattern="WHAT IS AN ARTIFICIAL INTELLIGENCE", score=0.99,
                 compatible=False)]


class OperatorTests(unittest.TestCase):
    # -- the operators ---------------------------------------------------------------------------
    def test_filter_keeps_matching_items_and_changes_nothing_else(self):
        items = candidates()
        snapshot = [dict(item) for item in items]
        result = operators.apply_filter(items, lambda item: item["compatible"])
        self.assertEqual(len(result["value"]), 1)
        self.assertEqual(len(result["dropped"]), 3)
        self.assertEqual(items, snapshot, "filter must be pure")
        self.assertEqual(result["provenance"]["rank"], "preserved")

    def test_map_transforms_each_item_and_may_not_change_the_count(self):
        items = candidates()
        result = operators.apply_map(items, lambda item: dict(ref=item["row"], score=item["score"]))
        self.assertEqual(len(result["value"]), len(items))
        self.assertIn("ref", result["value"][0])
        # MAP is one-in-one-out by construction, so the count is preserved even when a transform
        # returns a collection: changing the size is FILTER's job.
        nested = operators.apply_map(items, lambda item: [item])
        self.assertEqual(len(nested["value"]), len(items))

    def test_fold_preserves_the_accumulator_rank(self):
        items = candidates()
        folded = operators.apply_fold(items, operators.accumulate, dict(items=[], count=0))
        self.assertEqual(folded["value"]["count"], len(items))
        self.assertEqual(folded["provenance"]["rank"], "preserved")

    def test_accumulate_is_the_fold_state_update(self):
        state = operators.accumulate({"items": [], "count": 0}, "a")
        state = operators.accumulate(state, "b")
        self.assertEqual(state["items"], ["a", "b"])
        self.assertEqual(state["count"], 2)

    def test_reduce_collapses_along_a_declared_axis(self):
        items = candidates()
        best = operators.apply_reduce(items, axis="score", mode="max")
        self.assertEqual(best["value"]["selected"]["row"], 1)
        self.assertEqual(best["provenance"]["rank"], "collapsed")
        total = operators.apply_reduce(items, axis="score", mode="sum")
        self.assertAlmostEqual(total["value"]["total"], 1.0 + 0.995 + 0.994 + 0.99, places=6)
        with self.assertRaises(operators.OperatorError):
            operators.apply_reduce(items, axis="score", mode="median")
        empty = operators.apply_reduce([], axis="score")
        self.assertIsNone(empty["value"])

    # -- the pipeline ----------------------------------------------------------------------------
    def test_the_pipeline_runs_filter_map_fold_reduce_in_order(self):
        result = operators.pipeline(candidates(), keep=lambda item: item["compatible"],
                                    transform=lambda item: dict(kind="proposition",
                                                                ref=f"aiml://vector/{item['row']}",
                                                                score=item["score"]))
        self.assertEqual([stage["operator"] for stage in result["stages"]],
                         ["filter", "map", "fold", "reduce"])
        self.assertEqual(result["stages"][0]["count_before"], 4)
        self.assertEqual(result["stages"][0]["count_after"], 1)
        self.assertEqual(result["selected"]["selected"]["ref"], "aiml://vector/1")
        self.assertEqual(result["evidence"]["count"], 1)

    def test_the_pipeline_is_bounded_and_read_only(self):
        result = operators.pipeline(candidates(), keep=lambda item: True, budget=2)
        self.assertEqual(result["candidates_in"], 2, "the budget truncates the input")
        self.assertFalse(result["execution"])
        self.assertFalse(result["mutation"])
        self.assertEqual(result["authority"], "declaration_only")

    # -- URI resolution --------------------------------------------------------------------------
    def test_every_registered_scheme_resolves_to_data(self):
        for uri in ("kuhul://phases/pop", "aiml://category/what-is#1", "gml://enterprise/relations",
                    "micronaut://v1/chat", "srai://route/what-is"):
            result = operators.resolve_uri(uri)
            self.assertTrue(result["ok"], f"{uri}: {result.get('error')}")
            self.assertTrue(result["data"], uri)
            self.assertFalse(result["execution"], uri)
            self.assertEqual(result["authority"], "declaration_only", uri)

    def test_a_phase_uri_reads_the_manifest(self):
        result = operators.resolve_uri("kuhul://phases/sek")
        self.assertTrue(result["ok"])
        self.assertEqual(result["resolved"]["phase"], "Sek")
        self.assertTrue(result["resolved"]["bindings"])

    def test_unknown_schemes_are_refused(self):
        for uri in ("http://example.com/x", "ftp://x", "file:///etc/passwd", ""):
            result = operators.resolve_uri(uri)
            self.assertFalse(result["ok"], uri)
            self.assertTrue(result["error"], uri)
            self.assertEqual(result["authority"], "declaration_only", uri)

    def test_a_missing_resource_is_refused_with_a_reason_not_a_traceback(self):
        result = operators.resolve_uri("kuhul://phases/nope")
        self.assertFalse(result["ok"])
        self.assertIn("no manifest for phase", result["error"])
        self.assertNotIn("Errno", result["error"])

    def test_cycles_and_depth_are_bounded(self):
        cycle = operators.resolve_uri("aiml://x#1", seen={"aiml://x#1"})
        self.assertIn("cycle", cycle["error"])
        deep = operators.resolve_uri("aiml://x#1", depth=99)
        self.assertIn("depth limit", deep["error"])

    def test_a_walk_stops_at_the_first_refusal(self):
        result = operators.walk(["kuhul://phases/pop", "http://example.com/x",
                                 "kuhul://phases/wo"])
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["resolved"]), 1)
        self.assertEqual(len(result["refused"]), 1)
        self.assertEqual(result["chain"][-1], "http://example.com/x")
        self.assertFalse(result["execution"])
        self.assertEqual(result["authority"], "declaration_only")

    def test_summaries_state_that_resolution_grants_nothing(self):
        single = operators.summary(operators.resolve_uri("aiml://category/what-is#1"))
        self.assertIn("declaration_only", single)
        walked = operators.summary(operators.walk(["kuhul://phases/pop", "gml://x"]))
        self.assertIn("ok", walked)


if __name__ == "__main__":
    unittest.main()
