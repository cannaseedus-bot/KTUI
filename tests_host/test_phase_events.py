"""M73: the smallest honest phase trace - host observations, four families, no inference.

The rule under test: a model returning `{"phase": "Sek"}` is not evidence that Sek executed. Events come only
from the host, only where something happened, and an incomplete trace stays incomplete.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import phase_events  # noqa: E402
import phase_routing  # noqa: E402


class EventTests(unittest.TestCase):
    def setUp(self):
        phase_events.reset()

    def test_an_event_carries_its_provenance(self):
        record = phase_events.emit("turn-1", "phase_enter", phase="Sek")
        self.assertEqual(record["schema"], "kuhul://phase-event/v1")
        self.assertEqual(record["authority"], "observed")
        self.assertEqual(record["source"], "host")
        self.assertEqual(record["phase"], "Sek")
        self.assertEqual(record["sequence"], 1)
        self.assertIsInstance(record["monotonic"], float)

    def test_an_unregistered_phase_is_refused(self):
        with self.assertRaises(phase_events.EventError) as raised:
            phase_events.emit("turn-1", "phase_enter", phase="Zap")
        self.assertIn("Zap", str(raised.exception))

    def test_an_unknown_event_family_is_refused(self):
        with self.assertRaises(phase_events.EventError):
            phase_events.emit("turn-1", "phase_teleported", phase="Sek")

    def test_an_event_without_a_request_id_is_refused(self):
        with self.assertRaises(phase_events.EventError):
            phase_events.emit("", "phase_enter", phase="Sek")

    def test_a_phase_cannot_exit_before_it_enters(self):
        with self.assertRaises(phase_events.EventError):
            phase_events.emit("turn-1", "phase_exit", phase="Sek")

    def test_an_untrusted_source_is_refused(self):
        with self.assertRaises(phase_events.EventError):
            phase_events.emit("turn-1", "proposal_generated", source="model")

    def test_the_four_families_stay_distinct(self):
        phase_events.emit("turn-1", "phase_enter", phase="Sek")
        phase_events.emit("turn-1", "proposal_generated", detail={"operators": 4})
        phase_events.emit("turn-1", "proposal_validated", source="validator",
                          detail={"verdict": "exact"})
        phase_events.emit("turn-1", "phase_exit", phase="Sek", detail={"ok": True})
        families = [record["event"] for record in phase_events.events("turn-1")]
        self.assertEqual(families, ["phase_enter", "proposal_generated", "proposal_validated",
                                    "phase_exit"])

    def test_no_execution_event_is_emitted_by_these_helpers(self):
        phase_events.emit("turn-1", "phase_enter", phase="Sek")
        families = {record["event"] for record in phase_events.events("turn-1")}
        self.assertNotIn("execution_admitted", families,
                         "admission needs an explicit XCFE decision, not a validator verdict")


class ObserveTests(unittest.TestCase):
    def setUp(self):
        phase_events.reset()

    def test_an_empty_trace_is_unknown_not_complete(self):
        view = phase_events.observe("turn-none")
        self.assertFalse(view["observed"])
        self.assertFalse(view["complete"])
        self.assertEqual(view["state"], "no_observations")
        self.assertIn("not empty by design", view["note"])

    def test_an_open_phase_is_reported_active(self):
        phase_events.emit("turn-1", "phase_enter", phase="Yax")
        view = phase_events.observe("turn-1")
        self.assertEqual(view["state"], "active")
        self.assertEqual(view["active_phase"], "Yax")
        self.assertFalse(view["complete"])

    def test_a_failed_exit_is_reported_failed(self):
        phase_events.emit("turn-1", "phase_enter", phase="Sek")
        phase_events.emit("turn-1", "phase_exit", phase="Sek", detail={"ok": False})
        view = phase_events.observe("turn-1")
        self.assertEqual(view["state"], "failed")
        self.assertIsNone(view["active_phase"])

    def test_absent_phases_are_not_filled_in(self):
        phase_events.emit("turn-1", "phase_enter", phase="Pop")
        phase_events.emit("turn-1", "phase_exit", phase="Pop", detail={"ok": True})
        view = phase_events.observe("turn-1")
        self.assertEqual(view["phases"], ["Pop"])
        self.assertNotIn("Sek", view["phases"])
        self.assertNotIn("Ch'en", view["phases"])


class HostPathTests(unittest.TestCase):
    def setUp(self):
        phase_events.reset()

    def test_the_phase_chain_records_what_it_did(self):
        verdict = phase_routing.route("tell me about my dog", request_id="turn-2")
        self.assertIn(verdict["action"], ("chain", "fallback", "refuse"))
        view = phase_events.observe("turn-2")
        self.assertTrue(view["observed"])
        self.assertEqual(view["phases"], ["Pop"])
        self.assertTrue(view["complete"])
        self.assertEqual(view["families"], ["phase_enter", "phase_exit"])

    def test_a_call_without_a_request_id_records_nothing(self):
        phase_routing.route("tell me about my dog")
        self.assertEqual([record for record in phase_events.events("")], [])

    def test_the_trace_names_the_host_as_the_source(self):
        phase_routing.route("who are you", request_id="turn-3")
        for record in phase_events.events("turn-3"):
            self.assertEqual(record["source"], "host")
            self.assertEqual(record["authority"], "observed")

    def test_a_failing_resolution_exits_with_ok_false(self):
        original = phase_routing.phase_chain.resolve

        def broken(*args, **kwargs):
            raise RuntimeError("the chain is unreadable")

        phase_routing.phase_chain.resolve = broken
        try:
            with self.assertRaises(RuntimeError):
                phase_routing.route("anything", request_id="turn-4")
        finally:
            phase_routing.phase_chain.resolve = original
        view = phase_events.observe("turn-4")
        self.assertEqual(view["state"], "failed")
        self.assertTrue(view["failed"], "the phase failed and the trace records it")
        # the trace is complete - the phase entered and exited - but it did not succeed
        self.assertTrue(view["complete"])


class FailureAndCancellationTests(unittest.TestCase):
    """A request that fails or is cancelled must not leave a phase looking eternally active."""

    def setUp(self):
        phase_events.reset()

    def test_a_failure_is_its_own_event_family(self):
        phase_events.emit("turn-1", "phase_enter", phase="Sek")
        phase_events.emit("turn-1", "phase_failed", phase="Sek", detail={"outcome": "failed"})
        view = phase_events.observe("turn-1")
        self.assertEqual(view["state"], "failed")
        self.assertTrue(view["failed"])
        self.assertIsNone(view["active_phase"], "the phase is not left active")

    def test_a_cancellation_is_distinct_from_a_failure(self):
        phase_events.emit("turn-2", "phase_enter", phase="Yax")
        phase_events.emit("turn-2", "phase_exit", phase="Yax",
                          detail={"ok": False, "outcome": "cancelled"})
        view = phase_events.observe("turn-2")
        self.assertEqual(view["state"], "cancelled")
        self.assertTrue(view["cancelled"])
        self.assertFalse(view["failed"])

    def test_an_unknown_outcome_is_refused(self):
        with self.assertRaises(phase_events.EventError):
            phase_events.emit("turn-3", "phase_exit", phase="Pop", detail={"outcome": "vibes"})

    def test_a_raising_host_path_ends_the_phase(self):
        import phase_routing

        original = phase_routing.phase_chain.resolve

        def broken(*args, **kwargs):
            raise RuntimeError("the chain is unreadable")

        phase_routing.phase_chain.resolve = broken
        try:
            with self.assertRaises(RuntimeError):
                phase_routing.route("anything", request_id="turn-4")
        finally:
            phase_routing.phase_chain.resolve = original
        view = phase_events.observe("turn-4")
        self.assertEqual(view["state"], "failed")
        self.assertIsNone(view["active_phase"])

    def test_concurrent_turns_keep_independent_traces(self):
        import phase_routing

        phase_routing.route("who are you", request_id="turn-a")
        phase_routing.route("who are you", request_id="turn-b")
        a, b = phase_events.observe("turn-a"), phase_events.observe("turn-b")
        self.assertEqual(a["request_id"], "turn-a")
        self.assertEqual(b["request_id"], "turn-b")
        self.assertEqual(len(a["events"]), len(b["events"]))
        self.assertTrue(all(record["request_id"] == "turn-a" for record in a["events"]))
        self.assertTrue(all(record["request_id"] == "turn-b" for record in b["events"]))


class BoundedHistoryTests(unittest.TestCase):
    def setUp(self):
        phase_events.reset()

    def test_a_trace_is_bounded(self):
        for index in range(phase_events.MAX_EVENTS + 25):
            phase_events.emit("turn-long", "proposal_generated", detail={"index": index})
        events = phase_events.events("turn-long")
        self.assertEqual(len(events), phase_events.MAX_EVENTS)
        self.assertEqual(events[-1]["detail"]["index"], phase_events.MAX_EVENTS + 24)

    def test_the_number_of_traces_is_bounded(self):
        for index in range(phase_events.MAX_TRACES + 5):
            phase_events.emit(f"turn-{index}", "proposal_generated")
        self.assertLessEqual(len(phase_events._traces), phase_events.MAX_TRACES)

    def test_an_event_bumps_the_generation(self):
        import runtime_signals

        runtime_signals.reset("phase")
        before = runtime_signals.generation()
        phase_events.emit("turn-bump", "proposal_generated")
        self.assertGreater(runtime_signals.generation(), before,
                           "a committed phase event changes what the projection would show")


class WoInstrumentationTests(unittest.TestCase):
    """Wo is a real host handler now: enter, resolve, exit - and a failure still ends the phase."""

    def setUp(self):
        phase_events.reset()

    def test_a_wo_resolution_is_observed(self):
        import binding_resolver

        registry = binding_resolver.load()
        resolved = binding_resolver.binding(registry, "full_composition", request_id="wo-1")
        self.assertEqual(resolved["mode"], "deterministic")
        view = phase_events.observe("wo-1")
        self.assertEqual(view["phases"], ["Wo"])
        self.assertTrue(view["complete"])
        self.assertEqual(view["families"], ["phase_enter", "phase_exit"])

    def test_the_callers_return_value_is_unchanged(self):
        import binding_resolver

        registry = binding_resolver.load()
        with_id = binding_resolver.binding(registry, "uri_binding", request_id="wo-2")
        without = binding_resolver.binding(registry, "uri_binding")
        self.assertEqual(with_id, without)

    def test_a_resolution_without_a_request_id_records_nothing(self):
        import binding_resolver

        binding_resolver.binding(binding_resolver.load(), "refusal")
        self.assertEqual(phase_events.events(""), [])

    def test_interleaved_wo_requests_keep_independent_sequences(self):
        import binding_resolver

        registry = binding_resolver.load()
        binding_resolver.binding(registry, "full_composition", request_id="wo-a")
        binding_resolver.binding(registry, "refusal", request_id="wo-b")
        a, b = phase_events.events("wo-a"), phase_events.events("wo-b")
        self.assertEqual([record["request_id"] for record in a], ["wo-a", "wo-a"])
        self.assertEqual([record["request_id"] for record in b], ["wo-b", "wo-b"])
        self.assertEqual([record["sequence"] for record in a], [1, 2])
        self.assertEqual([record["sequence"] for record in b], [1, 2])

    def test_a_partial_failure_does_not_synthesize_later_phases(self):
        import binding_resolver
        import phase_routing

        phase_routing.route("tell me about my dog", request_id="turn-x")
        original = binding_resolver._resolve

        def broken(registry, family):
            raise RuntimeError("the target registry is unreadable")

        binding_resolver._resolve = broken
        try:
            with self.assertRaises(RuntimeError):
                binding_resolver.binding(binding_resolver.load(), "full_composition",
                                         request_id="turn-x")
        finally:
            binding_resolver._resolve = original
        view = phase_events.observe("turn-x")
        self.assertEqual(view["phases"], ["Pop", "Wo"], "no phase after the failure is invented")
        self.assertEqual(view["state"], "failed")
        self.assertNotIn("Yax", view["phases"])
        self.assertNotIn("Sek", view["phases"])
        self.assertNotIn("Xul", view["phases"])


if __name__ == "__main__":
    unittest.main()
