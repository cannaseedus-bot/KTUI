"""M30: `phase.resolve_aiml` - one input, one typed phase plan, no execution.

The plan is the integration point the review asked for: phases become the framework, and AIML/SRAI/
ELIZA/vectors supply the material. These guards hold it to four promises.

  typed + deterministic   six phases, fixed order, identical JSON on repeat
  evidence, not guesses   attributes come from memory; a cause that was never recorded is a problem
  delegation              greetings, directives and identity are the host's, not the plan's
  read-only               execution false, authority declaration_only, no memory writes
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import phase_resolve  # noqa: E402
import user_memory  # noqa: E402


class PhaseResolveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original = user_memory.EVENTS
        user_memory.EVENTS = Path(self.folder.name) / "user.events.jsonl"
        for predicate, value in (("name", "Rex"), ("personality", "playful"), ("size", "big")):
            user_memory.remember(user="bill", subject="pet", predicate=predicate, value=value)

    def tearDown(self):
        user_memory.EVENTS = self.original
        self.folder.cleanup()

    def plan(self, text, **kwargs):
        return phase_resolve.resolve_aiml(text, user="bill", **kwargs)

    # -- shape ------------------------------------------------------------------------------------
    def test_the_plan_is_typed_and_ordered(self):
        plan = self.plan("why does my dog act playful?")
        self.assertEqual(plan["schema"], "kuhul.phase-plan/1")
        self.assertEqual(plan["order"], ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        self.assertEqual(list(plan["phases"]), ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        for phase in plan["order"]:
            self.assertIsInstance(plan["phases"][phase], dict, phase)

    def test_the_plan_is_deterministic(self):
        first = phase_resolve.canonical(self.plan("why does my dog act playful?"))
        second = phase_resolve.canonical(self.plan("why does my dog act playful?"))
        self.assertEqual(first, second, "the same input must produce identical bytes")
        self.assertNotIn("timestamp", first.lower(), "no time-dependent field may enter a plan")

    def test_it_is_read_only(self):
        plan = self.plan("what is my pet like")
        self.assertFalse(plan["execution"])
        self.assertFalse(plan["mutation"])
        self.assertEqual(plan["authority"], "declaration_only")
        self.assertFalse(plan["phases"]["Ch'en"]["admitted"])
        self.assertFalse(plan["phases"]["Xul"]["persist"])

    # -- phases -----------------------------------------------------------------------------------
    def test_pop_finds_candidates_and_wo_binds_captures(self):
        plan = self.plan("my dogs name is max")
        pop, wo = plan["phases"]["Pop"], plan["phases"]["Wo"]
        self.assertIn("MY DOGS NAME IS *", pop["matched_patterns"])
        self.assertEqual(wo["captures"], ["max"], "the capture keeps the user's case")

    def test_wo_selects_eliza_fields(self):
        plan = self.plan("why does my big black dog act playful?")
        fields = plan["phases"]["Wo"]["fields"]
        self.assertEqual(fields["question_type"], "explanation")
        self.assertIn("playful", fields["attributes"])
        self.assertEqual(fields["reflected"].count("your"), 1, "my -> your reflection")

    def test_yax_routes_srai_and_lists_facts(self):
        plan = self.plan("what changed")
        routes = plan["phases"]["Yax"]["srai_routes"]
        self.assertTrue(routes, "WHAT CHANGED redirects to GIT STATUS")
        self.assertEqual(routes[0]["srai"], "GIT STATUS")
        self.assertIn(routes[0]["status"], {"RESOLVED", "REFUSED"})
        self.assertTrue(plan["phases"]["Yax"]["graph_facts"], "facts are carried, not fetched later")

    def test_yax_accepts_vector_candidates_without_promoting_them(self):
        def retriever(text):
            return [dict(vector_row=1, cosine_score=0.99, pattern="WHAT IS AI")]
        plan = self.plan("what is ai", retriever=retriever)
        self.assertEqual(len(plan["phases"]["Yax"]["vector_candidates"]), 1)
        kinds = {entry["kind"] for entry in plan["phases"]["Ch'en"]["evidence"]}
        self.assertNotIn("vector", kinds, "a vector candidate is never evidence")
        self.assertEqual(plan["phases"]["Xul"]["closure"], "supported",
                         "the answer still comes from recorded facts, not from the vector")

    def test_sek_proposes_operators_over_the_facts(self):
        plan = self.plan("what is my pet like")
        sek = plan["phases"]["Sek"]
        self.assertEqual([proposal["opcode"] for proposal in sek["operator_plan"]],
                         ["filter", "map", "fold"])
        self.assertEqual(sek["candidates"], 3)

    # -- the distinction the phases exist for ------------------------------------------------------
    def test_known_attributes_are_separated_from_an_unsupported_cause(self):
        plan = self.plan("why does my dog act playful?")
        chen, xul = plan["phases"]["Ch'en"], plan["phases"]["Xul"]
        self.assertTrue(chen["evidence"], "the attributes are recorded")
        codes = [problem["code"] for problem in chen["problems"]]
        self.assertIn("unsupported_explanation", codes)
        self.assertEqual(xul["closure"], "partial")
        self.assertIn("no recorded cause", xul["response"])
        self.assertFalse(xul["verified"], "a partial answer is not a verified one")

    def test_a_supported_answer_closes_as_supported(self):
        plan = self.plan("what is my pet like")
        self.assertEqual(plan["phases"]["Xul"]["closure"], "supported")
        self.assertTrue(plan["phases"]["Xul"]["verified"])

    def test_an_asked_subject_that_is_not_recorded_is_reported(self):
        plan = self.plan("what is my hamster like")
        codes = [problem["code"] for problem in plan["phases"]["Ch'en"]["problems"]]
        self.assertIn("subject_not_recorded", codes)
        self.assertEqual(plan["phases"]["Ch'en"]["subject_used"], "pet",
                         "the answer names the subject that is actually recorded")

    def test_a_greeting_closes_as_none(self):
        plan = self.plan("hello")
        self.assertEqual(plan["phases"]["Xul"]["closure"], "none")
        self.assertEqual(plan["phases"]["Xul"]["response"], "")

    def test_directives_and_identity_are_delegated(self):
        for text in ("who are you", "git status", "commit this", "my dogs name is max"):
            plan = self.plan(text)
            self.assertEqual(plan["phases"]["Xul"]["closure"], "delegated", text)
            self.assertEqual(plan["phases"]["Xul"]["response"], "", text)
            self.assertIn("host", plan["phases"]["Xul"]["note"], text)

    def test_an_empty_memory_does_not_invent_an_answer(self):
        plan = phase_resolve.resolve_aiml("what is my pet like", user="nobody")
        self.assertEqual(plan["phases"]["Ch'en"]["evidence"], [])
        self.assertIn("no_facts", [problem["code"] for problem in plan["phases"]["Ch'en"]["problems"]])
        self.assertEqual(plan["phases"]["Xul"]["closure"], "unknown")

    def test_summary_reports_all_six_phases(self):
        text = phase_resolve.summary(self.plan("why does my dog act playful?"))
        for phase in ("Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"):
            self.assertIn(phase, text)
        self.assertIn("authority declaration_only", text)


if __name__ == "__main__":
    unittest.main()
