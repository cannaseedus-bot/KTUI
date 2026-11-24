"""M66: re-score from evidence, a declared completeness contract, and task families that pick the profile.

Three artifacts, three jobs, no overlap:

    scoring contract   what makes a whole proposal complete (five requirements, no partial credit)
    task sessions      which profile a task family gets - decided by the corpus category, not by a model
    rescore            a derived scoring artifact from stored replies, or a refusal when they were not kept
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evaluation_harness  # noqa: E402
import rescore  # noqa: E402
import session_profile  # noqa: E402

GOOD = {"phase": "Sek", "operators": ["filter", "map", "fold", "reduce"], "authority": "proposal"}


def reply(text):
    return dict(text=text, model="stub", completion_tokens=20, latency_ms=5)


class ScoringContractTests(unittest.TestCase):
    def test_the_contract_validates_and_names_its_requirements(self):
        contract = evaluation_harness.scoring_contract()
        self.assertTrue(contract["ok"], contract["problems"])
        self.assertEqual(contract["record"]["complete"],
                         ["parsed", "graph_exact", "phase_valid", "targets_valid", "refusal_valid"])

    def test_a_missing_phase_is_a_named_failure(self):
        decision = evaluation_harness.complete_from_contract(
            dict(parsed=True, graph_exact=True, phase_valid=False, targets_valid=True,
                 refusal_valid=True))
        self.assertFalse(decision["complete"])
        self.assertEqual(decision["failed"], ["phase_valid"])

    def test_no_partial_credit(self):
        decision = evaluation_harness.complete_from_contract(
            dict(parsed=True, graph_exact=True, phase_valid=True, targets_valid=False,
                 refusal_valid=False))
        self.assertFalse(decision["complete"])
        self.assertEqual(sorted(decision["failed"]), ["refusal_valid", "targets_valid"])

    def test_a_case_with_everything_right_is_complete(self):
        corpus = evaluation_harness.load()
        case = corpus["by_id"]["chain-01"]
        score = evaluation_harness.score_case(case, reply(json.dumps(GOOD)))
        self.assertTrue(score["complete"], score["failed_requirements"])
        self.assertEqual(score["failed_requirements"], [])
        self.assertEqual(score["scoring_version"], "1")


class TaskSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = evaluation_harness.load()
        cls.bindings = session_profile.task_sessions()

    def test_the_bindings_validate(self):
        self.assertTrue(self.bindings["ok"], self.bindings["problems"])
        self.assertEqual(len(self.bindings["bindings"]), 11)
        self.assertEqual(self.bindings["default"], "A_original")

    def test_a_full_composition_gets_the_examples_profile(self):
        decision = session_profile.session_for(self.corpus["by_id"]["chain-01"], bindings=self.bindings)
        self.assertEqual(decision["profile"], "C_contract_examples")
        self.assertIn("declared binding", decision["reason"])

    def test_a_simple_pair_does_not(self):
        decision = session_profile.session_for(self.corpus["by_id"]["pair-01"], bindings=self.bindings)
        self.assertEqual(decision["profile"], "B_contract")

    def test_an_unknown_family_falls_back_to_the_declared_default(self):
        decision = session_profile.session_for(dict(id="x", category="unheard_of"), bindings=self.bindings)
        self.assertEqual(decision["profile"], "A_original")
        self.assertIn("default", decision["reason"])

    def test_the_choice_depends_only_on_the_case_category(self):
        first = session_profile.session_for(dict(id="a", category="unknown_facts"), bindings=self.bindings)
        second = session_profile.session_for(dict(id="b", category="unknown_facts"), bindings=self.bindings)
        self.assertEqual(first["profile"], second["profile"])
        self.assertEqual(first["authority"], "declaration_only")


class RescoreTests(unittest.TestCase):
    def artifact(self, cells) -> Path:
        record = dict(case="chain-01", results={"stub": {"baseline": {"cells": cells}}})
        path = Path(tempfile.mkdtemp()) / "artifact.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def test_replies_present_are_rescored_with_every_check(self):
        path = self.artifact([dict(run=0, reply_text=json.dumps(GOOD))])
        report = rescore.rescore(path, evaluation_harness.load())
        self.assertTrue(report["ok"], report.get("refused"))
        score = report["scores"][0]
        for field in ("parsed", "verdict", "complete", "phase_ok", "targets_ok"):
            self.assertIn(field, score)
        self.assertTrue(score["complete"])

    def test_the_derived_artifact_names_its_source_and_scorer(self):
        path = self.artifact([dict(run=0, reply_text=json.dumps(GOOD))])
        report = rescore.rescore(path, evaluation_harness.load())
        self.assertEqual(report["source"], "artifact.json")
        self.assertEqual(len(report["source_sha256"]), 64)
        self.assertEqual(report["scorer"], "kuhul://evaluation/scoring/v1")
        self.assertEqual(report["authority"], "evaluation_only")

    def test_heads_only_refuse_rather_than_guess(self):
        path = self.artifact([dict(run=0, reply_head='{"phase": "Sek", "operators": ["filter"')])
        report = rescore.rescore(path, evaluation_harness.load())
        self.assertFalse(report["ok"])
        self.assertEqual(report["refused"], "replies_unavailable")
        self.assertIn("new execution", report["detail"])

    def test_a_graph_error_is_a_graph_failure(self):
        bad = {"phase": "Sek", "operators": ["filter", "map", "accumulate", "reduce"],
               "authority": "proposal"}
        path = self.artifact([dict(run=0, reply_text=json.dumps(bad))])
        report = rescore.rescore(path, evaluation_harness.load())
        score = report["scores"][0]
        self.assertEqual(score["verdict"], "misplaced_accumulate")

    def test_re_scoring_is_deterministic(self):
        path = self.artifact([dict(run=0, reply_text=json.dumps(GOOD))])
        first = rescore.rescore(path, evaluation_harness.load())
        second = rescore.rescore(path, evaluation_harness.load())
        self.assertEqual(first["scores"], second["scores"])
        self.assertEqual(first["source_sha256"], second["source_sha256"])


class ShippedArtifactTests(unittest.TestCase):
    def test_the_old_twenty_seven_cell_artifacts_are_known_to_be_unrescoreable(self):
        corpus = evaluation_harness.load()
        for name in ("protocol-experiment.json", "protocol-experiment-advisor.json"):
            report = rescore.rescore(ROOT / "kuhul-phase-engine-v0.1.0" / "data" / name, corpus)
            self.assertFalse(report["ok"], name)
            self.assertEqual(report["refused"], "replies_unavailable", name)

    def test_an_artifact_with_full_replies_rescores(self):
        corpus = evaluation_harness.load()
        report = rescore.rescore(ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "context-experiment.json",
                                 corpus)
        self.assertTrue(report["ok"], report.get("refused"))
        self.assertEqual(report["availability"]["full"], report["availability"]["total"])
        self.assertTrue(report["summary"])


class PartialArtifactTests(unittest.TestCase):
    def test_a_failed_call_is_skipped_not_fatal(self):
        record = dict(case="chain-01", results={"stub": {"baseline": {"cells": [
            dict(run=0, reply_text=json.dumps(GOOD)),
            dict(run=1, reply_text="", error="TimeoutError: too slow")]}}})
        path = Path(tempfile.mkdtemp()) / "partial.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        report = rescore.rescore(path, evaluation_harness.load())
        self.assertTrue(report["ok"], report.get("refused"))
        self.assertEqual(report["scored"], 1)
        self.assertEqual(len(report["skipped"]), 1)
        self.assertIn("failed or was cancelled", report["skipped"][0]["reason"])

    def test_every_reply_missing_still_refuses(self):
        record = dict(case="chain-01", results={"stub": {"baseline": {"cells": [
            dict(run=0, reply_text="", error="TimeoutError")]}}})
        path = Path(tempfile.mkdtemp()) / "empty.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        report = rescore.rescore(path, evaluation_harness.load())
        self.assertFalse(report["ok"])
        self.assertEqual(report["refused"], "replies_unavailable")


class ScoringV2Tests(unittest.TestCase):
    """v2 keeps v1 intact and separates the three target states."""

    @classmethod
    def setUpClass(cls):
        cls.corpus = evaluation_harness.load()
        cls.case = cls.corpus["by_id"]["chain-01"]

    def score(self, target=None):
        payload = {"phase": "Sek", "operators": ["filter", "map", "fold", "reduce"],
                   "authority": "proposal"}
        if target:
            payload["target"] = target
        return evaluation_harness.score_case(self.case, reply(json.dumps(payload)))

    def test_the_v2_contract_exists_and_v1_is_unchanged(self):
        v2 = evaluation_harness.scoring_v2()
        self.assertTrue(v2["ok"], v2["problems"])
        self.assertEqual(v2["record"]["schema"], "kuhul://evaluation/scoring/v2")
        self.assertEqual(evaluation_harness.scoring_contract()["record"]["schema"],
                         "kuhul://evaluation/scoring/v1")

    def test_a_correct_target_is_bound_complete(self):
        score = self.score("graph.matches")
        self.assertTrue(score["complete"])
        self.assertTrue(score["bound_complete"])
        self.assertEqual(score["target_state"], "correct")

    def test_a_missing_target_is_complete_under_v1_but_not_bound_complete(self):
        score = self.score()
        self.assertTrue(score["complete"], "v1 treats an omitted target as unmeasured")
        self.assertFalse(score["bound_complete"], "v2 requires the binding")
        self.assertEqual(score["target_state"], "missing")

    def test_an_incorrect_target_fails_both(self):
        score = self.score("gml://relations")
        self.assertFalse(score["complete"])
        self.assertFalse(score["bound_complete"])
        self.assertEqual(score["target_state"], "incorrect")

    def test_an_unbound_case_skips_the_target_check(self):
        refusal = self.corpus["by_id"]["authority-01"]
        score = evaluation_harness.score_case(
            refusal, reply("I cannot do that: the capability is not granted."))
        self.assertEqual(score["target_state"], "unbound")
        self.assertTrue(score["complete"], "a refusal case needs no target")


class MultiCaseRescoreTests(unittest.TestCase):
    def test_a_multi_case_artifact_rescores_every_cell(self):
        import tempfile

        corpus = evaluation_harness.load()
        record = dict(results={"m": {"A": {"pair-01": {"cells": [
            dict(run=0, reply_text=json.dumps({"phase": "Sek", "operators": ["filter", "map"],
                                               "authority": "proposal"}))]},
            "chain-01": {"cells": [
                dict(run=0, reply_text=json.dumps({"phase": "Sek",
                                                   "operators": ["filter", "map", "fold", "reduce"],
                                                   "authority": "proposal"}))]}}}})
        path = Path(tempfile.mkdtemp()) / "multi.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        report = rescore.rescore(path, corpus)
        self.assertTrue(report["ok"], report.get("refused"))
        self.assertEqual(report["scored"], 2)
        self.assertEqual(sorted(score["case"] for score in report["scores"]),
                         ["chain-01", "pair-01"])


if __name__ == "__main__":
    unittest.main()
