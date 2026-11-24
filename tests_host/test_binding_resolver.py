"""M67: Wo binds the target, and a conflicting model target is recorded and refused.

The two rules the review set, as tests:

    the authorized set comes from the runtime     `kuhul://targets/v1` is read by the live path; the
                                                  evaluation corpus is not
    a conflict is evidence, not a correction      the raw target is kept, the conflict is recorded, and the
                                                  proposal is refused rather than rewritten
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import binding_resolver  # noqa: E402
import evaluation_harness  # noqa: E402


class RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = binding_resolver.load()

    def test_the_registry_loads_and_modes_match_the_allowlists(self):
        self.assertTrue(self.registry["ok"], self.registry["problems"])
        self.assertEqual(len(self.registry["families"]), 11)
        for name, entry in self.registry["families"].items():
            expected = ("unbound" if not entry["allowed"] else
                        "deterministic" if len(entry["allowed"]) == 1 else "constrained")
            self.assertEqual(entry["mode"], expected, name)

    def test_a_declared_mode_that_contradicts_the_allowlist_is_refused(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "targets.json")
                            .read_text(encoding="utf-8"))
        record["families"]["uri_binding"]["mode"] = "deterministic"    # it has two targets
        folder = Path(tempfile.mkdtemp()) / "targets.json"
        folder.write_text(json.dumps(record), encoding="utf-8")
        report = binding_resolver.load(folder)
        self.assertFalse(report["ok"])
        self.assertIn("mode_mismatch", [problem["code"] for problem in report["problems"]])

    def test_an_unknown_family_is_unbound_by_the_declared_default(self):
        record = binding_resolver.binding(self.registry, "unheard_of")
        self.assertEqual(record["mode"], "unbound")
        self.assertFalse(record["declared_family"])

    def test_the_live_path_does_not_read_the_corpus(self):
        source = (ROOT / "binding_resolver.py").read_text(encoding="utf-8")
        self.assertNotIn("evaluation/cases", source)
        self.assertNotIn("evaluation_harness", source,
                         "the resolver must not import the scorer or its expectations")


class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = binding_resolver.load()

    def test_one_allowed_target_is_resolved_by_wo(self):
        record = binding_resolver.binding(self.registry, "full_composition")
        context = binding_resolver.context(record)
        self.assertEqual(context["selection_mode"], "deterministic")
        self.assertEqual(context["resolved_target"], "graph.matches")

    def test_several_targets_are_offered_not_resolved(self):
        record = binding_resolver.binding(self.registry, "uri_binding")
        context = binding_resolver.context(record)
        self.assertEqual(context["selection_mode"], "constrained")
        self.assertIsNone(context["resolved_target"])
        self.assertEqual(len(context["allowed_targets"]), 2)

    def test_a_matching_target_passes_membership(self):
        record = binding_resolver.binding(self.registry, "full_composition")
        verdict = binding_resolver.check(dict(record, resolved_target="graph.matches"),
                                         dict(target="graph.matches"))
        self.assertTrue(verdict["ok"])
        self.assertFalse(verdict["conflict"])
        self.assertFalse(verdict["admitted"], "membership is not admission")

    def test_a_registered_but_unauthorized_target_is_a_conflict(self):
        record = binding_resolver.binding(self.registry, "full_composition")
        verdict = binding_resolver.check(dict(record, resolved_target="graph.matches"),
                                         dict(target="gml://relations"))
        self.assertFalse(verdict["ok"])
        self.assertTrue(verdict["conflict"])
        self.assertEqual(verdict["raw_target"], "gml://relations")
        self.assertIn("rejected, not rewritten", verdict["reason"])

    def test_the_resolved_target_is_never_substituted_for_the_raw_one(self):
        record = binding_resolver.binding(self.registry, "full_composition")
        proposal = dict(target="gml://relations")
        verdict = binding_resolver.check(dict(record, resolved_target="graph.matches"), proposal)
        self.assertEqual(proposal["target"], "gml://relations", "the proposal is untouched")
        self.assertEqual(verdict["raw_target"], "gml://relations")
        self.assertEqual(verdict["resolved_target"], "graph.matches")

    def test_a_missing_target_is_refused(self):
        record = binding_resolver.binding(self.registry, "full_composition")
        verdict = binding_resolver.check(dict(record, resolved_target="graph.matches"), dict())
        self.assertFalse(verdict["ok"])
        self.assertIn("no target", verdict["reason"])

    def test_an_unbound_family_skips_membership(self):
        record = binding_resolver.binding(self.registry, "refusal")
        verdict = binding_resolver.check(dict(record, resolved_target=None), dict())
        self.assertTrue(verdict["ok"])
        self.assertTrue(verdict.get("skipped"))

    def test_evidence_keeps_both_targets(self):
        record = binding_resolver.binding(self.registry, "full_composition")
        proposal = dict(target="gml://relations")
        verdict = binding_resolver.check(dict(record, resolved_target="graph.matches"), proposal)
        evidence = binding_resolver.evidence(record, proposal, verdict)
        self.assertEqual(evidence["raw_target"], "gml://relations")
        self.assertEqual(evidence["resolved_target"], "graph.matches")
        self.assertTrue(evidence["conflict"])
        self.assertFalse(evidence["accepted"])
        self.assertFalse(evidence["admitted"])

    def test_the_family_allowlist_is_not_the_case_expectation(self):
        corpus = evaluation_harness.load()
        case = corpus["by_id"]["uri_binding" if "uri_binding" in corpus["by_id"] else "uri-01"]
        record = binding_resolver.binding(self.registry, case["category"])
        # the runtime may permit two targets where the case allows one: the corpus narrows, it does not define
        self.assertIsInstance(record["allowed"], list)
        self.assertEqual(record["source"], "kuhul://targets/v1")


class ApplyBindingTests(unittest.TestCase):
    """Three outcomes, and a host-supplied binding is never credited as a model prediction."""

    @classmethod
    def setUpClass(cls):
        cls.registry = binding_resolver.load()
        cls.singleton = binding_resolver.binding(cls.registry, "full_composition")

    def test_a_correct_model_target_is_accepted_as_the_models(self):
        applied = binding_resolver.apply_binding(self.singleton, dict(target="graph.matches"))
        self.assertTrue(applied["ok"])
        self.assertEqual(applied["binding_source"], "model")
        self.assertEqual(applied["model_target"], "graph.matches")
        self.assertFalse(applied["conflict"])

    def test_an_omitted_target_is_supplied_by_wo_and_says_so(self):
        applied = binding_resolver.apply_binding(self.singleton, {})
        self.assertTrue(applied["ok"])
        self.assertEqual(applied["binding_source"], "wo_resolved")
        self.assertIsNone(applied["model_target"])
        self.assertEqual(applied["resolved_target"], "graph.matches")
        self.assertEqual(applied["plan"]["target"], "graph.matches")

    def test_a_wrong_target_is_rejected_and_never_replaced(self):
        applied = binding_resolver.apply_binding(self.singleton, dict(target="gml://relations"))
        self.assertFalse(applied["ok"])
        self.assertTrue(applied["conflict"])
        self.assertEqual(applied["model_target"], "gml://relations")
        self.assertEqual(applied["plan"]["target"], "gml://relations",
                         "the plan keeps what the model said; it is not rewritten into a pass")
        self.assertIn("rejected", applied["reason"])

    def test_a_multi_target_family_does_not_guess(self):
        constrained = binding_resolver.binding(self.registry, "uri_binding")
        applied = binding_resolver.apply_binding(constrained, {})
        self.assertFalse(applied["ok"], "with two allowed targets Wo must not pick one for the model")

    def test_an_unbound_family_binds_nothing(self):
        unbound = binding_resolver.binding(self.registry, "refusal")
        applied = binding_resolver.apply_binding(unbound, {})
        self.assertTrue(applied["ok"])
        self.assertEqual(applied["binding_source"], "none")

    def test_the_evidence_keeps_both_targets_and_the_source(self):
        applied = binding_resolver.apply_binding(self.singleton, {})
        evidence = binding_resolver.plan_evidence(self.singleton, applied)
        self.assertIsNone(evidence["model_target"])
        self.assertEqual(evidence["resolved_target"], "graph.matches")
        self.assertEqual(evidence["binding_source"], "wo_resolved")
        self.assertFalse(evidence["admitted"])
        self.assertEqual(evidence["authority"], "declaration_only")

    def test_a_singleton_binding_is_not_a_model_success(self):
        applied = binding_resolver.apply_binding(self.singleton, {})
        self.assertEqual(applied["binding_source"], "wo_resolved",
                         "runtime correctness must not be reported as model target accuracy")


if __name__ == "__main__":
    unittest.main()
