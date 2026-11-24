"""M93: the Micronaut destination through the existing engine, with its admission intact.

The three things the review asked to verify: one engine for the process (not one per turn), the engine's own
admission preserved rather than bypassed, and the typed result keeping its schema identity all the way to Ch'en.
"""
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import micronaut_server  # noqa: E402
import phase_events  # noqa: E402
import session_log  # noqa: E402


class MicronautRouteTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        session_log.SESSIONS_DIR = Path(self.folder.name) / "sessions"
        phase_events.reset()

    def tearDown(self):
        self.folder.cleanup()

    def turn(self, text, *, grants=("graph.relations.read",), request_id="m-1", app=None):
        async def drive():
            instance = app or chat_app.ChatApp()
            async with instance.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                instance.granted_capabilities = lambda: set(grants)
                instance.request_id = request_id
                result = instance.local_answer(text)
                return instance, result

        instance, result = asyncio.run(drive())
        return instance, result, phase_events.observe(request_id)

    def exits(self, trace):
        return {event["phase"]: event["detail"] for event in trace["events"]
                if event["event"] == "phase_exit"}

    def test_a_query_relations_turn_reaches_the_registered_handler(self):
        _, result, trace = self.turn("QUERY RELATIONS")
        self.assertEqual(result[0], "route")
        self.assertEqual(trace["phases"], ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        self.assertTrue(trace["complete"])
        exits = self.exits(trace)
        self.assertEqual(exits["Sek"]["scheme"], "micronaut")
        self.assertEqual(exits["Sek"]["target"], "micronaut://v1/aiml")
        self.assertTrue(exits["Ch'en"]["ok"])
        self.assertEqual(exits["Ch'en"]["actual_schema"], "kuhul://schema/candidates/v1")
        self.assertIn("resolve_aiml", str(exits["Ch'en"]["handler"]))
        self.assertIn("typed result kuhul://schema/candidates/v1", result[1])

    def test_the_typed_result_is_not_flattened(self):
        app, _, _ = self.turn("QUERY RELATIONS")
        payload = app.last_route["result"]["payload"]
        self.assertEqual(payload["$schema"], "kuhul://schema/candidates/v1")
        self.assertIsInstance(payload.get("items"), list)
        self.assertEqual(app.last_route["output_type"], "typed_result")

    def test_one_engine_serves_every_turn(self):
        created = []
        original = micronaut_server.Engine

        class Counting(original):
            def __init__(self, *args, **kwargs):
                created.append(id(self))
                super().__init__(*args, **kwargs)

        micronaut_server.Engine = Counting
        try:
            app = chat_app.ChatApp()
            self.turn("QUERY RELATIONS", request_id="m-a", app=app)
            self.turn("QUERY RELATIONS", request_id="m-b", app=app)
            self.assertEqual(len(created), 1, "a second engine per turn would double the admission accounting")
            self.assertIs(app.engine_host(), app.engine_host())
        finally:
            micronaut_server.Engine = original

    def test_engine_refusal_survives_bridge_authorization(self):
        # the bridge authorizes by capability; the engine refuses because the handler is not registered
        app, result, trace = self.turn("QUERY_UNREGISTERED")
        exits = self.exits(trace)
        self.assertFalse(exits["Ch'en"]["ok"], "the engine's refusal must not be papered over")
        self.assertEqual(exits["Ch'en"]["verdict"], "dispatch_error")
        self.assertIn("handler_not_registered", result[1])
        self.assertFalse(app.last_route["admitted"])
        self.assertEqual(trace["state"], "failed")

    def test_a_missing_grant_never_reaches_the_engine(self):
        calls = []
        app = chat_app.ChatApp()

        async def drive():
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app.granted_capabilities = lambda: set()
                app.request_id = "m-nogrant"
                app.route_invoke = lambda uri, payload: calls.append(uri) or {}
                return app.local_answer("QUERY RELATIONS")

        asyncio.run(drive())
        self.assertEqual(calls, [], "no grant, no engine call")

    def test_one_request_id_runs_through_the_micronaut_turn(self):
        _, _, trace = self.turn("QUERY RELATIONS", request_id="m-xyz")
        self.assertEqual({event["request_id"] for event in trace["events"]}, {"m-xyz"})


if __name__ == "__main__":
    unittest.main()
