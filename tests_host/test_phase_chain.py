"""M32: the phase chain resolver - both declaration layers, one carried context, no execution.

The review named two integration details; both are guards here.

1. **Pop and Wo declare the same redirect.** The resolver records which phase applied a binding and
   which merely shadowed it, and the duplicate is reported rather than silently ignored.
2. **A phase transition is not a pattern match.** Every phase appears in the plan even when nothing in
   it matches, with the carried context intact, so the chain is operationally connected.

And the standing rule: the plan is a proposal. `execution: false`, `authority: declaration_only`.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import phase_chain  # noqa: E402


class PhaseChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chain = phase_chain.load()

    # -- the chain --------------------------------------------------------------------------------
    def test_the_chain_connects_all_six_phases(self):
        self.assertTrue(self.chain["ok"], self.chain["problems"])
        self.assertEqual(self.chain["phases"], ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        self.assertEqual(len(self.chain["banks"]), 6)
        for bank in self.chain["banks"]:
            self.assertTrue(Path(bank).is_file(), bank)

    def test_every_manifest_declares_the_shared_contract(self):
        for manifest in self.chain["manifests"]:
            self.assertEqual(manifest["authority"], "declaration_only")
        self.assertEqual(self.chain["authority"], "declaration_only")

    # -- advancing mode: the input moves with the redirect -----------------------------------------
    def test_the_input_advances_through_a_redirect(self):
        plan = phase_chain.resolve("who is bill")
        visits = {visit["phase"]: visit for visit in plan["visits"]}
        self.assertEqual(visits["Pop"]["applied"][0]["pattern"], "WHO IS *")
        self.assertEqual(visits["Pop"]["applied"][0]["resolved"], "WHAT IS bill")
        self.assertEqual(visits["Wo"]["no_match"], ["WHO IS *"],
                         "after the redirect the old input no longer matches")
        self.assertEqual(visits["Yax"]["applied"][0]["pattern"], "WHAT IS *")
        # A directive is handed to the host, so it does not re-feed the input; the srai does.
        self.assertEqual(plan["context"]["final_input"], "WHAT IS bill")
        self.assertEqual(plan["closure"]["kind"], "delegated")
        self.assertEqual(plan["closure"]["directive"], "QUERY bill")

    def test_every_phase_is_visited_even_without_a_match(self):
        plan = phase_chain.resolve("who is bill")
        self.assertEqual([visit["phase"] for visit in plan["visits"]],
                         ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        for visit in plan["visits"]:
            self.assertIn("applied", visit)
            self.assertIn("no_match", visit)
        self.assertEqual(plan["visits"][-1]["phase"], "Xul")
        self.assertEqual(plan["visits"][-1]["applied"], [], "Xul declares no bindings")

    def test_a_pattern_matches_only_in_the_phase_that_declares_it(self):
        plan = phase_chain.resolve("tell me about my dog")
        visits = {visit["phase"]: visit for visit in plan["visits"]}
        self.assertEqual(visits["Sek"]["applied"][0]["pattern"], "TELL ME ABOUT MY DOG")
        self.assertEqual(visits["Sek"]["applied"][0]["resolved"], "COMPOSE pet")
        self.assertEqual(visits["Pop"]["applied"], [], "Sek's binding is not Pop's")
        self.assertEqual(plan["closure"]["kind"], "delegated")

    # -- point 1: the duplicated redirect ---------------------------------------------------------
    def test_a_duplicated_binding_is_applied_once_and_reported(self):
        plan = phase_chain.resolve("who is bill", use_original=True)
        self.assertEqual(len(plan["duplicates"]), 1)
        duplicate = plan["duplicates"][0]
        self.assertEqual(duplicate["pattern"], "WHO IS *")
        self.assertEqual(duplicate["first_phase"], "Pop")
        self.assertEqual(duplicate["again_in"], "Wo")
        visits = {visit["phase"]: visit for visit in plan["visits"]}
        self.assertEqual(len(visits["Pop"]["applied"]), 1)
        self.assertEqual(visits["Wo"]["applied"], [], "the second declaration is shadowed, not re-run")
        self.assertEqual(len(visits["Wo"]["shadowed"]), 1)

    def test_an_unduplicated_chain_reports_no_duplicates(self):
        self.assertEqual(phase_chain.resolve("tell me about my dog")["duplicates"], [])

    # -- capabilities ------------------------------------------------------------------------------
    def test_capabilities_are_collected_only_where_declared(self):
        plan = phase_chain.resolve("who is bill")
        phases = {entry["phase"] for entry in plan["context"]["capabilities"]}
        self.assertEqual(phases, {"Yax"})
        self.assertEqual(plan["closure"]["capabilities"], ["graph.relations.read"])

    # -- the plan ----------------------------------------------------------------------------------
    def test_the_plan_is_deterministic(self):
        first = phase_chain.canonical(phase_chain.resolve("who is bill"))
        second = phase_chain.canonical(phase_chain.resolve("who is bill"))
        self.assertEqual(first, second)

    def test_the_plan_is_read_only(self):
        plan = phase_chain.resolve("who is bill")
        self.assertFalse(plan["execution"])
        self.assertFalse(plan["mutation"])
        self.assertEqual(plan["authority"], "declaration_only")
        self.assertFalse(plan["closure"].get("verified", False))

    def test_caller_context_is_carried(self):
        plan = phase_chain.resolve("who is bill", context={"user": "bill", "session": 7})
        self.assertEqual(plan["carried"], {"session": 7, "user": "bill"})

    def test_an_unmatched_input_closes_as_none(self):
        plan = phase_chain.resolve("explain quantum chromodynamics")
        applied = [entry for visit in plan["visits"] for entry in visit["applied"]]
        self.assertEqual(applied, [])
        self.assertEqual(plan["closure"]["kind"], "none")

    def test_the_summary_names_all_six_phases(self):
        text = phase_chain.summary(phase_chain.resolve("who is bill"))
        for phase in ("Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"):
            self.assertIn(phase, text)
        self.assertIn("declaration_only", text)


if __name__ == "__main__":
    unittest.main()
