"""M62: a generation counter gates the rebuild, and the digest still gates the repaint.

Two levels, deliberately separate:

    generation   cheap: did anything bump?          skips the registry walk entirely
    digest       semantic: did the meaning change?  decides whether the widget repaints

A bump that changes nothing observable therefore costs one rebuild and zero repaints - which is what makes a
2 s tick affordable. And the counter is a hint: it can be wrong in the safe direction (a missed bump means a
stale frame, not a wrong one).
"""
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evidence_record  # noqa: E402
import model_lifecycle  # noqa: E402
import runtime_signals  # noqa: E402


class FakeHost:
    def __init__(self, listening=()):
        self.open = set(listening)
        self.launches = []
        self.now = 1000.0

    def listening(self, port):
        return port in self.open

    def launch(self, name, spec):
        self.launches.append(name)
        self.open.add(spec["port"])
        return dict(pid=1)

    def stop(self, name, spec):
        self.open.discard(spec["port"])
        return dict(stopped=True)

    def clock(self):
        return self.now


class SignalTests(unittest.TestCase):
    def setUp(self):
        runtime_signals.reset("test")

    def test_a_bump_moves_the_generation(self):
        start = runtime_signals.generation()
        runtime_signals.bump("unit")
        self.assertEqual(runtime_signals.generation(), start + 1)
        self.assertEqual(runtime_signals.state()["reason"], "unit")

    def test_concurrent_bumps_are_not_lost(self):
        runtime_signals.reset("race")

        def hammer():
            for _ in range(50):
                runtime_signals.bump("thread")

        threads = [threading.Thread(target=hammer) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(runtime_signals.generation(), 300)

    def test_lifecycle_transitions_bump(self):
        runtime_signals.reset("lifecycle")
        lifecycle = model_lifecycle.Lifecycle(model_lifecycle.load(), host=FakeHost())
        before = runtime_signals.generation()
        lifecycle.ensure("planner")
        after_ensure = runtime_signals.generation()
        lifecycle.acquire("planner")
        after_acquire = runtime_signals.generation()
        lifecycle.release("planner")
        after_release = runtime_signals.generation()
        self.assertGreater(after_ensure, before)
        self.assertGreater(after_acquire, after_ensure)
        self.assertGreater(after_release, after_acquire)

    def test_an_idle_stop_bumps(self):
        runtime_signals.reset("stop")
        host = FakeHost()
        declaration = model_lifecycle.load()
        lifecycle = model_lifecycle.Lifecycle(declaration, host=host)
        lifecycle.ensure("worker")
        host.now += declaration["by_name"]["worker"]["idle_timeout_seconds"] + 10
        before = runtime_signals.generation()
        lifecycle.release_idle()
        self.assertGreater(runtime_signals.generation(), before)

    def test_an_evidence_append_bumps(self):
        runtime_signals.reset("evidence")
        folder = tempfile.TemporaryDirectory()
        original = evidence_record.LOG
        evidence_record.LOG = Path(folder.name) / "records.jsonl"
        try:
            before = runtime_signals.generation()
            evidence_record.append(evidence_record.build(input_text="x", request_id="r1"))
            self.assertGreater(runtime_signals.generation(), before)
        finally:
            evidence_record.LOG = original
            folder.cleanup()


class PollGateTests(unittest.TestCase):
    def app(self):
        import chat_app
        import session_log

        session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
        return chat_app.ChatApp()

    def test_an_unchanged_generation_skips_the_rebuild(self):
        import asyncio

        import runtime_tree

        runtime_signals.reset("gate")
        builds = []
        original = runtime_tree.watch

        def counted(**kwargs):
            builds.append(1)
            return original(**kwargs)

        async def drive():
            app = self.app()
            runtime_tree.watch = counted
            try:
                async with app.run_test(size=(120, 50)) as pilot:
                    await pilot.pause()
                    app.poll_runtime()
                    app.poll_runtime()
                    app.poll_runtime()
                    return app.runtime_polls, app.runtime_renders, app.runtime_skips
            finally:
                runtime_tree.watch = original
        polls, renders, skips = asyncio.run(drive())
        self.assertEqual(polls, 3)
        self.assertEqual(len(builds), 1, "one registry walk for an idle tick sequence")
        self.assertEqual(renders, 1)
        self.assertEqual(skips, 2)

    def test_a_bump_rebuilds_and_a_semantic_change_repaints(self):
        import asyncio

        import runtime_tree

        runtime_signals.reset("bump")
        snapshots = []
        original = runtime_tree.watch

        def scripted(**kwargs):
            snapshot = original(**kwargs)
            snapshots.append(snapshot["digest"])
            # the second build reports a different digest, as a real state change would
            if len(snapshots) == 2:
                return dict(snapshot, digest="f" * 64)
            return snapshot

        async def drive():
            app = self.app()
            runtime_tree.watch = scripted
            try:
                async with app.run_test(size=(120, 50)) as pilot:
                    await pilot.pause()
                    app.poll_runtime()
                    runtime_signals.bump("state changed")
                    app.poll_runtime()
                    return app.runtime_polls, app.runtime_renders, app.runtime_skips
            finally:
                runtime_tree.watch = original
        polls, renders, skips = asyncio.run(drive())
        self.assertEqual(polls, 2)
        self.assertEqual(renders, 2, "a changed digest repaints")
        self.assertEqual(skips, 0)

    def test_a_bump_without_a_semantic_change_repaints_nothing(self):
        import asyncio

        runtime_signals.reset("noise")

        async def drive():
            app = self.app()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                app.poll_runtime()
                runtime_signals.bump("a record was written")
                app.poll_runtime()
                return app.runtime_polls, app.runtime_renders, app.runtime_skips
        polls, renders, skips = asyncio.run(drive())
        self.assertEqual(polls, 2)
        self.assertEqual(renders, 1, "the digest is still the gate for repainting")
        self.assertEqual(skips, 0)


class CommittedChangeTests(unittest.TestCase):
    """The generation reflects committed observed changes - not method calls, and not intentions."""

    def test_a_failed_start_does_not_announce_readiness(self):
        import json

        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "models.json")
                            .read_text(encoding="utf-8"))
        record["models"]["planner"]["startup_timeout_seconds"] = 1
        folder = Path(tempfile.mkdtemp()) / "models.json"
        folder.write_text(json.dumps(record), encoding="utf-8")
        runtime_signals.reset("failed")
        host = FakeHost()                       # never opens the port
        host.launch = lambda name, spec: dict(pid=1)
        lifecycle = model_lifecycle.Lifecycle(model_lifecycle.load(folder), host=host)
        before = runtime_signals.generation()
        outcome = lifecycle.ensure("planner")
        after = runtime_signals.generation()
        self.assertTrue(outcome.get("timeout"))
        self.assertEqual(after, before + 1, "exactly one bump, and it is the failure")
        self.assertIn("launch_failed", runtime_signals.state()["reason"])
        self.assertNotEqual(lifecycle.state_of("planner"), "hot",
                            "a failed start must not read as hot")

    def test_a_successful_start_bumps_once_after_readiness(self):
        runtime_signals.reset("ready")
        lifecycle = model_lifecycle.Lifecycle(model_lifecycle.load(), host=FakeHost())
        before = runtime_signals.generation()
        lifecycle.ensure("planner")
        self.assertEqual(runtime_signals.generation(), before + 1)
        self.assertIn("ready", runtime_signals.state()["reason"])
        self.assertEqual(lifecycle.state_of("planner"), "hot")

    def test_an_idle_shutdown_is_a_committed_change(self):
        runtime_signals.reset("shutdown")
        host = FakeHost()
        declaration = model_lifecycle.load()
        lifecycle = model_lifecycle.Lifecycle(declaration, host=host)
        lifecycle.ensure("worker")
        host.now += declaration["by_name"]["worker"]["idle_timeout_seconds"] + 5
        before = runtime_signals.generation()
        sweep = lifecycle.release_idle()
        self.assertEqual(len(sweep["stopped"]), 1)
        self.assertGreater(runtime_signals.generation(), before)
        self.assertTrue(runtime_signals.state()["reason"].startswith("stop:"))
        self.assertEqual(lifecycle.state_of("worker"), "cold")


class ReconciliationTests(unittest.TestCase):
    """A counter in one process cannot see another process's edits, so a slow rebuild stays."""

    def test_the_poll_reconciles_every_n_ticks(self):
        import asyncio

        import chat_app
        import runtime_tree

        runtime_signals.reset("reconcile")
        builds = []
        original = runtime_tree.watch

        def counted(**kwargs):
            builds.append(1)
            return original(**kwargs)

        async def drive():
            import session_log
            session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
            app = chat_app.ChatApp()
            runtime_tree.watch = counted
            try:
                async with app.run_test(size=(120, 50)) as pilot:
                    await pilot.pause()
                    for _ in range(chat_app.RECONCILE_EVERY * 2):
                        app.poll_runtime()
                    return app.runtime_polls, app.runtime_skips, app.runtime_reconciles
            finally:
                runtime_tree.watch = original
        polls, skips, reconciles = asyncio.run(drive())
        expected_builds = 1 + (polls - 1) // chat_app.RECONCILE_EVERY
        self.assertEqual(len(builds), expected_builds, "one initial build plus one per reconcile")
        self.assertEqual(reconciles, (polls - 1) // chat_app.RECONCILE_EVERY)
        self.assertEqual(skips, polls - len(builds))

    def test_a_reconcile_without_a_change_still_does_not_repaint(self):
        import asyncio

        import chat_app
        import runtime_tree

        runtime_signals.reset("quiet")

        async def drive():
            import session_log
            session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                for _ in range(chat_app.RECONCILE_EVERY + 2):
                    app.poll_runtime()
                return app.runtime_renders, app.runtime_reconciles
        renders, reconciles = asyncio.run(drive())
        self.assertGreaterEqual(reconciles, 1)
        self.assertEqual(renders, 1, "the digest, not the counter, decides a repaint")


if __name__ == "__main__":
    unittest.main()
