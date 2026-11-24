"""M53: the operator contract as a session template - system rules plus demonstrations, re-sent per call.

The guards are about the protocol again, because a session that is assembled differently per profile would
make the comparison meaningless:

    the session is the only variable   one validator, one case set, one budget, one model
    the contract travels with request  a running server keeps no history, so the template is explicit
    examples are real demonstrations   a user turn and a matching assistant proposal, in that order
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evaluation_harness  # noqa: E402
import plan_graph  # noqa: E402
import proposal_eval  # noqa: E402
import session_profile  # noqa: E402


def reply(operators, phase="Sek"):
    return dict(text=json.dumps({"phase": phase, "operators": operators,
                                 "authority": "proposal"}),
                model="stub", completion_tokens=25, latency_ms=9, finish_reason="stop")


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = session_profile.load()

    def test_the_profiles_validate(self):
        self.assertTrue(self.profiles["ok"], self.profiles["problems"])
        self.assertEqual(sorted(self.profiles["profiles"]),
                         ["A_original", "B_contract", "C_contract_examples"])
        self.assertEqual(self.profiles["contract_uri"], "kuhul://operators/v1")

    def test_only_the_third_profile_carries_demonstrations(self):
        profiles = self.profiles["profiles"]
        self.assertEqual(len(profiles["A_original"]["examples"]), 0)
        self.assertEqual(len(profiles["B_contract"]["examples"]), 0)
        self.assertEqual(len(profiles["C_contract_examples"]["examples"]), 2)

    def test_the_contract_profile_states_the_containment_rule(self):
        system = self.profiles["profiles"]["B_contract"]["system"]
        self.assertIn("FOLD contains ACCUMULATE", system)
        self.assertIn("FILTER -> MAP -> FOLD -> REDUCE", system)
        self.assertIn('Authority is always "proposal"', system)

    def test_each_example_is_a_user_turn_and_a_matching_proposal(self):
        for pair in self.profiles["profiles"]["C_contract_examples"]["examples"]:
            self.assertEqual([message["role"] for message in pair], ["user", "assistant"])
            proposed = plan_graph.parse_sequence(pair[1]["content"])
            self.assertIsNotNone(proposed, "an example must be a plan the validator accepts")
            self.assertTrue(plan_graph.compare(proposed["operators"],
                                               expected=["filter", "map", "fold", "reduce"])
                            is not None)

    def test_a_profile_without_a_system_prompt_still_gets_one(self):
        profile = self.profiles["profiles"]["A_original"]
        conversation = session_profile.messages(profile, "task")
        self.assertEqual(conversation[0]["role"], "system")
        self.assertEqual(conversation[0]["content"], proposal_eval.SYSTEM,
                         "A is the pre-contract prompt, not an empty one")

    def test_the_task_is_the_last_message(self):
        for name, profile in self.profiles["profiles"].items():
            conversation = session_profile.messages(profile, "the task")
            self.assertEqual(conversation[-1], {"role": "user", "content": "the task"}, name)

    def test_examples_come_between_the_system_prompt_and_the_task(self):
        conversation = session_profile.messages(
            self.profiles["profiles"]["C_contract_examples"], "the task")
        roles = [message["role"] for message in conversation]
        self.assertEqual(roles, ["system", "user", "assistant", "user", "assistant", "user"])

    def test_a_broken_example_is_refused(self):
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "session-profiles.json")
                            .read_text(encoding="utf-8"))
        record["profiles"]["C_contract_examples"]["examples"][0] = [
            {"role": "assistant", "content": "{}"}, {"role": "user", "content": "x"}]
        folder = Path(tempfile.mkdtemp()) / "profiles.json"
        folder.write_text(json.dumps(record), encoding="utf-8")
        report = session_profile.load(folder)
        self.assertFalse(report["ok"])
        self.assertIn("example", [problem["code"] for problem in report["problems"]])


class ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = evaluation_harness.load()

    def test_the_session_is_the_only_variable(self):
        seen = []

        def complete(conversation):
            seen.append(conversation)
            return reply(["filter", "map", "fold", "reduce"])

        report = session_profile.run("stub", self.corpus, repeats=1, complete_for=complete)
        self.assertEqual(report["cases"], list(session_profile.CASES))
        self.assertEqual(len(seen), len(session_profile.CASES) * 3)
        self.assertEqual(report["results"]["C_contract_examples"]["chain-01"]["messages"], 6)
        self.assertEqual(report["results"]["B_contract"]["chain-01"]["messages"], 2)

    def test_a_contract_following_model_is_scored_exact(self):
        report = session_profile.run("stub", self.corpus, repeats=1,
                                     complete_for=lambda conversation: reply(["filter", "map"]))
        self.assertEqual(report["results"]["B_contract"]["pair-01"]["complete"], 1)
        self.assertEqual(report["results"]["B_contract"]["chain-01"]["complete"], 0,
                         "the short answer is not a full chain")

    def test_a_failed_call_is_a_failed_cell(self):
        def explode(conversation):
            raise TimeoutError("no answer")

        report = session_profile.run("slow", self.corpus, repeats=1, complete_for=explode)
        for cases in report["results"].values():
            for cell in cases.values():
                self.assertEqual(cell["complete"], 0)
                self.assertIn("TimeoutError", cell["cells"][0]["error"])

    def test_the_report_does_not_overclaim(self):
        report = session_profile.run("stub", self.corpus, repeats=1,
                                     complete_for=lambda conversation: reply(["filter", "map"]))
        self.assertIn("the session is the only variable", report["note"])
        self.assertFalse(report["execution"])
        self.assertEqual(report["authority"], "declaration_only")

    def test_the_summary_lists_every_profile_and_case(self):
        report = session_profile.run("stub", self.corpus, repeats=1,
                                     complete_for=lambda conversation: reply(["filter", "map"]))
        text = session_profile.summary(report)
        for name in session_profile.load()["profiles"]:
            self.assertIn(name, text)
        for case in session_profile.CASES:
            self.assertIn(case, text)


import tempfile  # noqa: E402  (used by the broken-example test)

if __name__ == "__main__":
    unittest.main()
