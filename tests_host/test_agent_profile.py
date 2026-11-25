"""M94: AGENT.md as a declaration with a working consumer - identity, persona, route preferences, no grants.

The file names routes, never targets; its parent must be a registered handler; a preference that does not resolve is
refused at load; and a preference can steer which declared route a turn takes while still needing the host grant.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import agent_profile  # noqa: E402
import micro_agent_bridge  # noqa: E402

VALID = """# AGENT.md

agent_id: daemon-bot
parent_micronaut: micronaut://v1/aiml

## Persona

Analytical and conversational.

## Preferred routes

reasoning_route: ASK_PLANNER
conversation_route: ASK_WORKER

## Authority

Declarations only.
"""


class LoadTests(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_a_valid_declaration_loads_with_its_preferences(self):
        loaded = agent_profile.load(self.write(VALID))
        self.assertTrue(loaded["ok"], loaded["problems"])
        self.assertEqual(loaded["agent"]["agent_id"], "daemon-bot")
        self.assertEqual(loaded["preferences"], {"reasoning": "ASK_PLANNER", "conversation": "ASK_WORKER"})
        self.assertEqual(loaded["authority"], "declaration_only")
        self.assertEqual(loaded["grants"], [])
        self.assertIn("Analytical", loaded["persona"])

    def test_the_shipped_declaration_is_valid_and_points_at_real_routes(self):
        loaded = agent_profile.load()
        self.assertTrue(loaded["ok"], loaded["problems"])
        for kind, route in loaded["preferences"].items():
            self.assertIn(route, micro_agent_bridge.DECLARED_ROUTES, kind)

    def test_a_preference_may_not_name_a_target(self):
        text = VALID.replace("reasoning_route: ASK_PLANNER", "reasoning_route: model://planner")
        loaded = agent_profile.load(self.write(text))
        self.assertFalse(loaded["ok"])
        self.assertEqual(loaded["refused"], "preference_is_target")

    def test_an_undeclared_route_is_refused(self):
        text = VALID.replace("ASK_PLANNER", "ASK_GHOST")
        loaded = agent_profile.load(self.write(text))
        self.assertEqual(loaded["refused"], "route_not_declared")

    def test_the_parent_must_be_a_registered_handler(self):
        text = VALID.replace("micronaut://v1/aiml", "micronaut://v1/does-not-exist")
        loaded = agent_profile.load(self.write(text))
        self.assertEqual(loaded["refused"], "parent_not_registered")

    def test_the_parent_must_be_a_micronaut_uri(self):
        text = VALID.replace("micronaut://v1/aiml", "model://planner")
        self.assertEqual(agent_profile.load(self.write(text))["refused"], "parent_scheme")

    def test_a_persona_may_not_declare_authority(self):
        for key in ("capabilities", "grants", "execution", "api_key"):
            text = VALID + f"\n{key}: [something]\n"
            self.assertEqual(agent_profile.load(self.write(text))["refused"], "agent_authority_key", key)

    def test_an_authority_section_is_refused(self):
        text = VALID + "\n## grants\n\nmodel.inference\n"
        self.assertEqual(agent_profile.load(self.write(text))["refused"], "agent_authority_section")

    def test_a_missing_file_is_a_named_refusal(self):
        loaded = agent_profile.load(Path(tempfile.gettempdir()) / "no-such-AGENT.md")
        self.assertEqual(loaded["refused"], "agent_missing")
        self.assertIsNone(agent_profile.route_for("reasoning", profile=loaded))

    def test_route_for_prefers_only_declared_routes(self):
        loaded = agent_profile.load(self.write(VALID))
        self.assertEqual(agent_profile.route_for("reasoning", profile=loaded), "ASK_PLANNER")
        self.assertIsNone(agent_profile.route_for("nonexistent", profile=loaded))


class PreferenceRoutingTests(unittest.TestCase):
    """The consumer: a preference chooses which declared route a turn takes, and cannot avoid the grant check."""

    def setUp(self):
        import asyncio
        import phase_events
        import session_log

        self.asyncio, self.phase_events, self.session_log = asyncio, phase_events, session_log
        self.folder = tempfile.TemporaryDirectory()
        session_log.SESSIONS_DIR = Path(self.folder.name) / "sessions"
        phase_events.reset()

    def tearDown(self):
        self.folder.cleanup()

    def turn(self, text, *, grants=("model.inference",)):
        import chat_app

        calls = []

        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app.route_completer = lambda alias, payload: calls.append(alias) or "a plan"
                app.granted_capabilities = lambda: set(grants)
                app.request_id = "agent-turn"
                return app.local_answer(text)

        result = self.asyncio.run(drive())
        return result, calls, self.phase_events.observe("agent-turn")

    def test_reasoning_resolves_through_the_agents_preference(self):
        result, calls, trace = self.turn("REASONING")
        self.assertEqual(result[0], "route")
        self.assertEqual(calls, ["planner"], "the preference chose ASK_PLANNER, which targets planner")
        self.assertEqual(trace["phases"], ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])

    def test_conversation_resolves_to_the_worker_route(self):
        _, calls, _ = self.turn("CONVERSATION")
        self.assertEqual(calls, ["worker"])

    def test_a_preference_does_not_bypass_the_grant(self):
        result, calls, trace = self.turn("REASONING", grants=())
        self.assertEqual(calls, [], "identity cannot supply a capability")
        exits = {event["phase"]: event["detail"] for event in trace["events"]
                 if event["event"] == "phase_exit"}
        self.assertEqual(exits["Ch'en"]["verdict"], "capability_not_granted")
        self.assertIn("No route result", result[1])


if __name__ == "__main__":
    unittest.main()
