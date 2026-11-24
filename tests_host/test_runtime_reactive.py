"""M56: the green screen is reactive - a semantic digest, and a render only when the state moves.

The three guards the review asked for, plus the subtlety:

    no-change stability   identical runtime state produces an identical digest and no refresh
    transition visibility a model going HOT -> COLD changes the digest, so the panel updates on its own
    authority preserved   building or refreshing the projection cannot wake a model, take a lease or mutate
    volatile fields out   record counts and timestamps are excluded, or the screen would refresh forever
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime_tree  # noqa: E402


class FakeHost:
    def __init__(self, ports):
        self.open = set(ports)

    def listening(self, port):
        return port in self.open


class DigestTests(unittest.TestCase):
    def test_identical_state_produces_an_identical_digest(self):
        first = runtime_tree.watch(host=FakeHost({9032, 9040, 9041}))
        second = runtime_tree.watch(host=FakeHost({9032, 9040, 9041}))
        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual(len(first["digest"]), 64)

    def test_a_transition_changes_the_digest(self):
        hot = runtime_tree.watch(host=FakeHost({9032, 9040, 9041}))
        cold = runtime_tree.watch(host=FakeHost({9040}))
        self.assertNotEqual(hot["digest"], cold["digest"],
                            "a model leaving the running state must be visible")
        states = {node["id"]: node["fields"].get("state")
                  for node in cold["tree"]["nodes"] if node["kind"] == "model"}
        self.assertEqual(states["model://advisor"], "cold")
        self.assertEqual(states["model://worker"], "hot")

    def test_volatile_fields_are_excluded(self):
        tree = runtime_tree.projection(host=FakeHost({9040}))
        baseline = runtime_tree.semantic_digest(tree)
        for node in tree["nodes"]:
            if node["kind"] == "evidence":
                node["fields"]["records"] = (node["fields"].get("records") or 0) + 41
                node["fields"]["last_request_id"] = "changed"
        self.assertEqual(runtime_tree.semantic_digest(tree), baseline,
                         "a new record count is not a semantic change to the screen")

    def test_a_semantic_field_change_is_detected(self):
        tree = runtime_tree.projection(host=FakeHost({9040}))
        baseline = runtime_tree.semantic_digest(tree)
        for node in tree["nodes"]:
            if node["id"] == "model://worker":
                node["fields"]["state"] = "cold"
        self.assertNotEqual(runtime_tree.semantic_digest(tree), baseline)

    def test_building_the_projection_never_manages_the_lifecycle(self):
        import model_lifecycle

        calls = []

        def forbidden(*args, **kwargs):
            calls.append(args)
            raise AssertionError("the projection must not manage models")

        originals = {name: getattr(model_lifecycle.Lifecycle, name)
                     for name in ("ensure", "acquire", "release", "release_idle")}
        for name in originals:
            setattr(model_lifecycle.Lifecycle, name, forbidden)
        try:
            snapshot = runtime_tree.watch(host=FakeHost({9040}))
        finally:
            for name, original in originals.items():
                setattr(model_lifecycle.Lifecycle, name, original)
        self.assertEqual(calls, [], "no lifecycle method was reached")
        self.assertEqual(len(snapshot["digest"]), 64)


class ReactiveAppTests(unittest.TestCase):
    def app(self):
        import chat_app
        import session_log
        import tempfile

        session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
        return chat_app.ChatApp()

    def test_an_unchanged_projection_is_not_rendered_twice(self):
        import asyncio

        async def drive():
            app = self.app()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app.poll_runtime()
                app.poll_runtime()
                app.poll_runtime()
                return app.runtime_polls, app.runtime_renders, app.runtime_digest
        polls, renders, digest = asyncio.run(drive())
        self.assertEqual(polls, 3)
        self.assertEqual(renders, 1, "one render for one state")
        self.assertEqual(len(digest), 64)

    def test_a_state_change_triggers_a_second_render(self):
        import asyncio

        async def drive():
            app = self.app()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app.poll_runtime()
                original = runtime_tree.watch

                def moved(**kwargs):
                    snapshot = original(**kwargs)
                    return dict(snapshot, digest="0" * 64)

                runtime_tree.watch = moved
                try:
                    app.poll_runtime()
                finally:
                    runtime_tree.watch = original
                return app.runtime_polls, app.runtime_renders
        polls, renders = asyncio.run(drive())
        self.assertEqual(polls, 2)
        self.assertEqual(renders, 2, "a changed digest refreshes the panel")

    def test_the_panel_shows_the_model_states(self):
        import asyncio

        async def drive():
            app = self.app()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app.poll_runtime()
                import chat_app as module
                widget = app.query_one("#green-screen", module.Static)
                return str(widget.render())
        text = asyncio.run(drive())
        self.assertIn("model 3", text)
        self.assertIn("worker", text)

    def test_every_poll_rebuilds_rather_than_caching_a_graph(self):
        import asyncio

        async def drive():
            app = self.app()
            calls = []
            original = runtime_tree.watch

            def counted(**kwargs):
                calls.append(1)
                return original(**kwargs)

            runtime_tree.watch = counted
            try:
                async with app.run_test(size=(120, 50)) as pilot:
                    await pilot.pause()
                    app.poll_runtime()
                    app.poll_runtime()
            finally:
                runtime_tree.watch = original
            return len(calls)
        self.assertEqual(asyncio.run(drive()), 2,
                         "the registries stay authoritative; the widget holds only the digest")


if __name__ == "__main__":
    unittest.main()
