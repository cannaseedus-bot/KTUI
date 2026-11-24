"""M91: one live KTUI turn uses the bridge - Pop, Wo, Yax, Sek, Ch'en, Xul under one request id.

The acceptance criteria from the review, as guards: one request id throughout, exactly one backend invocation for a
declared route, the result entering conversation context, a missing grant invoking nothing, an empty candidate
closing as a failure, and a literal model:// URI in ordinary text invoking nothing.
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


class RouteTurnTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        session_log.SESSIONS_DIR = Path(self.folder.name) / "sessions"
        phase_events.reset()

    def tearDown(self):
        self.folder.cleanup()

    def turn(self, text, *, grants=("model.inference",), answer="1. filter\n2. fold", request_id="route-1"):
        calls = []

        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app.route_completer = lambda alias, payload: calls.append((alias, payload)) or answer
                app.granted_capabilities = lambda: set(grants)
                app.request_id = request_id
                result = app.local_answer(text)
                return app, result

        app, result = asyncio.run(drive())
        return app, result, calls, phase_events.observe(request_id)

    def exits(self, trace):
        return {event["phase"]: event["detail"] for event in trace["events"]
                if event["event"] == "phase_exit"}

    def test_a_declared_route_turn_runs_all_six_phases_with_one_invocation(self):
        app, result, calls, trace = self.turn("ASK PLANNER")
        self.assertEqual(result[0], "route")
        self.assertEqual(trace["phases"], ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        self.assertTrue(trace["complete"])
        self.assertEqual(len(calls), 1, "exactly one backend invocation")
        self.assertEqual(calls[0][0], "planner")

    def test_the_aiml_chain_preserves_both_hops(self):
        _, _, _, trace = self.turn("ASK PLANNER")
        yax = self.exits(trace)["Yax"]
        self.assertEqual(yax["hops"], 2, "spoken name redirects to the token, the token routes")
        self.assertEqual(yax["reply"], "ROUTE ASK_PLANNER")

    def test_the_result_enters_the_conversation_context(self):
        app, result, _, _ = self.turn("ASK PLANNER")
        self.assertIn("1. filter", result[1])
        self.assertTrue(any(message.get("role") == "assistant" and "filter" in str(message.get("content"))
                            for message in app.messages),
                        "the model result is context before composition")

    def test_one_request_id_runs_through_every_phase(self):
        _, _, _, trace = self.turn("ASK PLANNER", request_id="route-xyz")
        self.assertEqual({event["request_id"] for event in trace["events"]}, {"route-xyz"})

    def test_a_missing_grant_invokes_nothing_and_closes_as_refused(self):
        _, result, calls, trace = self.turn("ASK PLANNER", grants=())
        self.assertEqual(calls, [], "no grant, no invocation")
        exits = self.exits(trace)
        self.assertEqual(exits["Ch'en"]["verdict"], "capability_not_granted")
        self.assertFalse(exits["Ch'en"]["verified"])
        self.assertEqual(exits["Xul"]["turn_outcome"], "refused")
        self.assertFalse(exits["Xul"]["ok"])
        self.assertIn("No route result", result[1])
        self.assertEqual(trace["state"], "failed")

    def test_an_empty_candidate_closes_as_a_failure(self):
        _, result, calls, trace = self.turn("ASK PLANNER", answer="   ")
        self.assertEqual(len(calls), 1)
        exits = self.exits(trace)
        self.assertEqual(exits["Sek"]["ok"], True, "the dispatch completed")
        self.assertFalse(exits["Ch'en"]["ok"], "an empty candidate is not verified")
        self.assertEqual(exits["Xul"]["turn_outcome"], "refused")

    def test_a_literal_uri_in_ordinary_text_invokes_nothing(self):
        app, result, calls, trace = self.turn("what is model://planner")
        self.assertEqual(calls, [])
        self.assertNotIn("Yax", trace["phases"], "no route turn happened")
        self.assertNotIn("Sek", trace["phases"])

    def test_execute_route_declines_ordinary_text(self):
        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                return app.execute_route("tell me about my dog")

        self.assertIsNone(asyncio.run(drive()))

    def test_the_bridge_result_is_kept_for_inspection(self):
        app, _, _, _ = self.turn("ASK PLANNER")
        self.assertEqual(app.last_route["status"], "completed")
        self.assertEqual(app.last_route["source"], "aiml_srai")
        self.assertFalse(app.last_route["admitted"])


if __name__ == "__main__":
    unittest.main()
