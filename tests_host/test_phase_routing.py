"""M34 / M35: the daemon consumes the phase chain, and a grant gates what a route may do.

M34 - consumption. `local_answer` consults the chain first and keeps both the verdict and the plan. The
fallback policy is explicit: nothing matched, or a read-only capability is unavailable, and the existing
answer path runs with the reason recorded.

M35 - grants. A `requires_grant` capability bound into a route blocks execution when the grant is
absent, and an authorised grant permits only its own scope. A pattern matching in AIML never grants
anything by itself.
"""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_app  # noqa: E402
import phase_routing  # noqa: E402
import user_memory  # noqa: E402


def manifest(folder: Path, name: str, phase: str, *, bindings=(), next_uri=None, aiml=()):
    record = {"schema": "kuhul-phases/v1", "phase": phase, "uri": f"kuhul://phases/{name}",
              "aiml": list(aiml), "bindings": list(bindings), "next": next_uri,
              "authority": "declaration_only"}
    (folder / f"{name}.json").write_text(json.dumps(record), encoding="utf-8")


class M34ChainConsumption(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original = user_memory.EVENTS
        user_memory.EVENTS = Path(self.folder.name) / "user.events.jsonl"

    def tearDown(self):
        user_memory.EVENTS = self.original
        self.folder.cleanup()

    def run_turn(self, text):
        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                outcome = app.local_answer(text)
                return app, outcome

        return asyncio.run(drive())

    def test_the_daemon_consults_the_chain_and_keeps_the_plan(self):
        app, outcome = self.run_turn("tell me about my dog")
        self.assertIsNotNone(app.last_routing, "the chain was consulted")
        self.assertEqual(app.last_routing["action"], "chain")
        self.assertIsNotNone(app.last_plan, "the plan is preserved for inspection")
        self.assertEqual(app.last_plan["phases"], ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        self.assertEqual(app.last_plan["closure"]["kind"], "delegated")
        self.assertEqual(outcome[0], "compose", "the existing answer path still answers")

    def test_the_fallback_policy_is_recorded_when_nothing_matches(self):
        app, outcome = self.run_turn("hello")
        self.assertEqual(app.last_routing["action"], "fallback")
        self.assertIn("no chain binding matched", app.last_routing["reason"])
        self.assertEqual(outcome[0], "aiml", "the banks answer through the fallback")

    def test_a_tool_turn_falls_back_because_the_chain_does_not_own_it(self):
        app, outcome = self.run_turn("git status")
        self.assertEqual(app.last_routing["action"], "fallback")
        self.assertEqual(outcome[0], "tool")

    def test_the_verdict_and_plan_are_read_only(self):
        app, _ = self.run_turn("who is bill")
        self.assertFalse(app.last_routing["execution"])
        self.assertFalse(app.last_routing["mutation"])
        self.assertEqual(app.last_routing["authority"], "declaration_only")
        self.assertFalse(app.last_plan["execution"])

    def test_grants_are_named_not_implied(self):
        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 46)) as pilot:
                await pilot.pause()
                return app, app.granted_capabilities()

        app, granted = asyncio.run(drive())
        self.assertIn("graph.relations.read", granted)
        self.assertNotIn("repo.write", granted, "no grant until /allow git")
        self.assertNotIn("memory.write", granted, "no grant until /allow memory")


class M35GrantAwareRouting(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        manifest(self.root, "pop", "Pop",
                 bindings=[{"pattern": "COMMIT THE TREE", "directive": "GITOP commit",
                            "capability": "repo.write"}],
                 next_uri="kuhul://phases/xul")
        manifest(self.root, "xul", "Xul", bindings=[])

    def tearDown(self):
        self.folder.cleanup()

    def route(self, granted=()):
        return phase_routing.route("commit the tree", granted=set(granted), folder=self.root)

    def test_an_absent_grant_blocks_and_never_falls_back(self):
        verdict = self.route()
        self.assertEqual(verdict["action"], "refuse")
        self.assertIn("repo.write", verdict["reason"])
        self.assertIn("no fallback", verdict["reason"])
        self.assertEqual(verdict["missing"], ["repo.write"])

    def test_the_matching_pattern_alone_grants_nothing(self):
        verdict = self.route()
        self.assertEqual(verdict["closure"], "delegated", "the pattern did match")
        self.assertEqual(verdict["execution"], False)
        self.assertEqual(verdict["authority"], "declaration_only")

    def test_an_authorised_grant_permits_its_own_scope(self):
        verdict = self.route(granted={"repo.write"})
        self.assertEqual(verdict["action"], "chain")
        self.assertEqual(verdict["missing"], [])
        self.assertIn("exact scope", verdict["reason"])

    def test_a_different_grant_does_not_cover_the_route(self):
        verdict = self.route(granted={"memory.write"})
        self.assertEqual(verdict["action"], "refuse")
        self.assertEqual(verdict["missing"], ["repo.write"])

    def test_a_read_only_capability_falls_back_instead_of_refusing(self):
        folder = Path(self.folder.name) / "read"
        folder.mkdir()
        manifest(folder, "pop", "Pop",
                 bindings=[{"pattern": "WHO IS *", "directive": "QUERY {star:1}",
                            "capability": "graph.relations.read"}],
                 next_uri="kuhul://phases/xul")
        manifest(folder, "xul", "Xul", bindings=[])
        verdict = phase_routing.route("who is bill", granted=set(), folder=folder)
        self.assertEqual(verdict["action"], "fallback")
        self.assertIn("read-only capability unavailable", verdict["reason"])

    def test_a_directive_with_no_capability_proceeds_on_the_chain(self):
        folder = Path(self.folder.name) / "plain"
        folder.mkdir()
        manifest(folder, "pop", "Pop",
                 bindings=[{"pattern": "WHO IS *", "directive": "QUERY {star:1}"}],
                 next_uri="kuhul://phases/xul")
        manifest(folder, "xul", "Xul", bindings=[])
        verdict = phase_routing.route("who is bill", granted=set(), folder=folder)
        self.assertEqual(verdict["action"], "chain")
        self.assertEqual(verdict["required"], [])

    def test_capability_classes_are_decided_by_name(self):
        self.assertEqual(phase_routing.capability_class("repo.write"), "execution")
        self.assertEqual(phase_routing.capability_class("memory.write"), "execution")
        self.assertEqual(phase_routing.capability_class("graph.relations.read"), "read")


if __name__ == "__main__":
    unittest.main()
