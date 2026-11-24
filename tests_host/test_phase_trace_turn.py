"""M87: the compose path performs real work in Pop, Yax, Sek, Ch'en and Xul, and the trace says so.

Each observed phase wraps a function with its own contract:

    Pop    phase_routing.route        the chain verdict
    Yax    compose.retrieve           ranked relations above the declared threshold
    Sek    compose.compose            fold the kept candidates into a sentence
    Ch'en  compose.verify             the composition contract: unsupported fails, supersession warns
    Xul    compose.summary            the emitted text

Wo is deliberately absent here: nothing on the chat path classifies a live turn into a task family, so there is no
binding to observe. A phase lights up when it does work, not when a label is available.
"""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import phase_events  # noqa: E402
import session_log  # noqa: E402
import user_memory  # noqa: E402


class ComposeTraceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        session_log.SESSIONS_DIR = Path(self.folder.name) / "sessions"
        user_memory.EVENTS = Path(self.folder.name) / "user.events.jsonl"
        phase_events.reset()

    def tearDown(self):
        self.folder.cleanup()

    def turn(self, text="tell me about my dog", *, record=("name", "colour")):
        for predicate in record:
            user_memory.remember(user="42", subject="pet", predicate=predicate,
                                 value={"name": "Rex", "colour": "black"}[predicate])

        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app.user_id = "42"
                app.query_one("Input").value = text
                await pilot.press("enter")
                await pilot.pause()
                return app.request_id, phase_events.observe(app.request_id or "")

        return asyncio.run(drive())

    def test_a_compose_turn_traces_six_phases_in_order(self):
        _, trace = self.turn()
        self.assertEqual(trace["phases"], ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"],
                         "Pop recognises, Wo binds, then the computation runs")
        self.assertTrue(trace["complete"], "every phase that entered also exited")
        self.assertEqual(trace["families"], ["phase_enter", "phase_exit"])

    def test_every_event_is_a_host_observation(self):
        _, trace = self.turn()
        for event in trace["events"]:
            self.assertEqual(event["source"], "host")
            self.assertEqual(event["authority"], "observed")

    def test_the_phases_report_real_work(self):
        _, trace = self.turn()
        by_phase = {}
        for event in trace["events"]:
            if event["event"] == "phase_exit":
                by_phase[event["phase"]] = event["detail"]
        self.assertEqual(by_phase["Wo"]["family"], "compose")
        self.assertEqual(by_phase["Wo"]["targets"], ["graph.matches"])
        self.assertEqual(by_phase["Yax"]["kept"], 2, "two relations were retrieved")
        self.assertEqual(by_phase["Yax"]["considered"], 2)
        self.assertEqual(by_phase["Sek"]["candidates"], 2)
        self.assertGreater(by_phase["Sek"]["attributes"], 0)
        self.assertEqual(by_phase["Ch'en"]["problems"], 0)
        self.assertGreater(by_phase["Xul"]["emitted"], 0)

    def test_a_missing_relation_is_not_invented(self):
        # only the name is recorded: retrieval keeps one relation, and no phase claims a second
        _, trace = self.turn(record=("name",))
        exits = {event["phase"]: event["detail"] for event in trace["events"]
                 if event["event"] == "phase_exit"}
        self.assertEqual(exits["Yax"]["kept"], 1)
        self.assertEqual(exits["Sek"]["candidates"], 1)

    def test_an_ambiguous_turn_binds_nothing(self):
        _, trace = self.turn(text="what do you know about my dog")
        exits = {event["phase"]: event["detail"] for event in trace["events"]
                 if event["event"] == "phase_exit"}
        self.assertEqual(exits["Wo"]["status"], "ambiguous")
        self.assertFalse(exits["Wo"]["ok"], "an ambiguous binding is not a bound turn")
        self.assertEqual(sorted(exits["Wo"]["candidates"]), ["compose", "memory_query"])
        self.assertEqual(exits["Wo"]["targets"], [], "no target is invented for an ambiguous turn")

    def test_no_request_id_means_no_events(self):
        import compose

        settings = {"weights": {}, "min_score": 0.0, "max_candidates": 5}
        compose.retrieve("42", "dog", settings)
        self.assertEqual(phase_events.events(""), [])

    def test_a_verification_failure_ends_ch_en_and_still_closes_xul(self):
        # no relations at all: verify cannot pass, and the trace must not pretend otherwise
        _, trace = self.turn(record=())
        exits = {event["phase"]: event["detail"] for event in trace["events"]
                 if event["event"] == "phase_exit"}
        self.assertIn("Ch'en", exits)
        self.assertIn("Xul", exits, "the turn still closes")
        self.assertFalse(exits["Xul"]["ok"], "closing a failed composition is not a success")


if __name__ == "__main__":
    unittest.main()
