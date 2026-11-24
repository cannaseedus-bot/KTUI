"""M88: Wo classifies a live turn, deterministically, and never invents a target.

The classifier is a real host function with a typed contract (family, route, binding source, candidates, status) and
no model in the loop. Ambiguity is reported, not resolved: two families reading the same sentence bind nothing.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import turn_classifier  # noqa: E402


class ClassificationTests(unittest.TestCase):
    def test_a_compose_request_binds_with_its_declared_target(self):
        binding = turn_classifier.classify("tell me about my dog")
        self.assertEqual(binding["status"], "bound")
        self.assertEqual(binding["task_family"], "compose")
        self.assertEqual(binding["target_family"], "full_composition")
        self.assertEqual(binding["allowed_targets"], ["graph.matches"])
        self.assertEqual(binding["route_id"], "compose.paragraph")
        self.assertEqual(binding["binding_source"], "rule")

    def test_an_explicit_command_outranks_a_rule(self):
        binding = turn_classifier.classify("/compose dog")
        self.assertEqual(binding["family"] if "family" in binding else binding["task_family"], "compose")
        self.assertEqual(binding["binding_source"], "explicit_command")

    def test_a_git_request_binds_to_the_git_route(self):
        binding = turn_classifier.classify("git status")
        self.assertEqual(binding["task_family"], "git_operation")
        self.assertEqual(binding["route_id"], "gitops")

    def test_an_identity_question_binds_without_a_target(self):
        binding = turn_classifier.classify("who are you")
        self.assertEqual(binding["task_family"], "identity")
        self.assertEqual(binding["allowed_targets"], [])
        self.assertIn("binds no target", binding["reason"])

    def test_an_unclassified_sentence_falls_back_to_conversation(self):
        binding = turn_classifier.classify("write a poem about rain")
        self.assertEqual(binding["status"], "bound")
        self.assertEqual(binding["task_family"], "conversation")

    def test_ambiguity_is_reported_and_binds_nothing(self):
        binding = turn_classifier.classify("what do you know about my dog")
        self.assertEqual(binding["status"], "ambiguous")
        self.assertIsNone(binding["task_family"])
        self.assertEqual(sorted(binding["candidate_families"]), ["compose", "memory_query"])
        self.assertEqual(binding["allowed_targets"], [])
        self.assertIn("must not choose", binding["reason"])

    def test_an_unknown_command_is_unsupported(self):
        binding = turn_classifier.classify("/nonsense")
        self.assertEqual(binding["status"], "unsupported")
        self.assertIn("not a classified command", binding["reason"])

    def test_an_empty_turn_is_unsupported(self):
        binding = turn_classifier.classify("   ")
        self.assertEqual(binding["status"], "unsupported")

    def test_a_constrained_target_family_publishes_no_choice(self):
        binding = turn_classifier.classify("what is my name?")
        self.assertEqual(binding["task_family"], "memory_query")
        self.assertEqual(binding["target_family"], "uri_binding")
        self.assertEqual(binding["allowed_targets"], [],
                         "uri_binding allows two targets, so Wo must not pick one")
        self.assertIn("does not pick one", binding["reason"])

    def test_classification_grants_nothing(self):
        for text in ("tell me about my dog", "git status", "who are you", "hello"):
            binding = turn_classifier.classify(text)
            self.assertEqual(binding["authority"], "declaration_only")
            self.assertNotIn("capabilities", binding)

    def test_the_summary_names_the_status_and_the_source(self):
        text = turn_classifier.summary(turn_classifier.classify("tell me about my dog"))
        self.assertIn("bound", text)
        self.assertIn("compose", text)
        self.assertIn("rule", text)
        self.assertIn("graph.matches", text)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        import phase_events

        phase_events.reset()

    def test_observation_needs_a_request_id(self):
        import phase_events

        turn_classifier.observe(turn_classifier.classify("hello"), None)
        self.assertEqual(phase_events.events(""), [])

    def test_an_ambiguous_binding_is_recorded_as_failed(self):
        import phase_events

        turn_classifier.observe(turn_classifier.classify("what do you know about my dog"), "turn-1")
        view = phase_events.observe("turn-1")
        exit_event = [event for event in view["events"] if event["event"] == "phase_exit"][0]
        self.assertEqual(exit_event["detail"]["status"], "ambiguous")
        self.assertFalse(exit_event["detail"]["ok"])
        self.assertEqual(exit_event["detail"]["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
