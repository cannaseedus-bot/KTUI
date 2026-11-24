"""M60: the stream holds the lease, and the app owns one lifecycle plus its sweep.

The integration guard the review singled out: a lease must cover the **stream**, not the call that opens
it. A client that stops reading closes the iterator, and the lease still has to come back.

    stream completion   lease released, measurements kept
    cancellation        close() releases the lease with the chunks that were read
    stream error        released, error recorded
    cold-start failure  no dispatch, no lease taken, latency stays None
    concurrent streams  one launch, each caller its own lease
"""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evidence_record  # noqa: E402
import inference_session  # noqa: E402
import model_lifecycle  # noqa: E402


class FakeHost:
    def __init__(self, *, listening=(), ready=True):
        self.open = set(listening)
        self.ready = ready
        self.launches = []
        self.now = 1000.0

    def listening(self, port):
        return port in self.open

    def launch(self, name, spec):
        self.launches.append((name, spec["port"]))
        if self.ready:
            self.open.add(spec["port"])
        return dict(pid=3000 + len(self.launches))

    def stop(self, name, spec):
        self.open.discard(spec["port"])
        return dict(stopped=True)

    def clock(self):
        return self.now


def chunks(count=4, delay=0.0):
    def open_stream(conversation):
        for index in range(count):
            if delay:
                time.sleep(delay)
            yield f"c{index}"
    return open_stream


class StreamLeaseTests(unittest.TestCase):
    def setUp(self):
        self.declaration = model_lifecycle.load()
        self.host = FakeHost()
        self.lifecycle = model_lifecycle.Lifecycle(self.declaration, host=self.host)
        self.waker = inference_session.Waker(self.lifecycle)

    def test_a_completed_stream_releases_its_lease(self):
        call = inference_session.StreamingCall(self.waker, "planner",
                                               [{"role": "user", "content": "x"}],
                                               chunks(4), record=False)
        self.assertEqual(list(call), ["c0", "c1", "c2", "c3"])
        self.assertTrue(call.lease_released)
        self.assertEqual(call.chunks, 4)
        self.assertEqual(self.lifecycle.leases.get("planner"), 0)
        for field in ("first_token_ms", "stream_ms", "total_ms"):
            self.assertIsInstance(call.measurements[field], int, field)

    def test_cancellation_releases_the_lease(self):
        call = inference_session.StreamingCall(self.waker, "planner",
                                               [{"role": "user", "content": "x"}],
                                               chunks(6), record=False)
        iterator = iter(call)
        next(iterator)
        next(iterator)
        iterator.close()                       # a client that stops reading
        self.assertTrue(call.lease_released, "a cancelled stream must still return its lease")
        self.assertEqual(call.chunks, 2)
        self.assertEqual(self.lifecycle.leases.get("planner"), 0)

    def test_a_stream_error_releases_and_reports(self):
        def explode(conversation):
            yield "c0"
            raise RuntimeError("the server dropped the connection")

        call = inference_session.StreamingCall(self.waker, "planner",
                                               [{"role": "user", "content": "x"}],
                                               explode, record=False)
        with self.assertRaises(RuntimeError):
            list(call)
        self.assertTrue(call.lease_released)
        self.assertIn("dropped", call.error)
        self.assertEqual(self.lifecycle.leases.get("planner"), 0)

    def test_a_cold_start_failure_takes_no_lease(self):
        declaration = model_lifecycle.load(_cold_declaration())
        host = FakeHost(ready=False)
        lifecycle = model_lifecycle.Lifecycle(declaration, host=host)
        waker = inference_session.Waker(lifecycle)
        call = inference_session.StreamingCall(waker, "planner",
                                               [{"role": "user", "content": "x"}],
                                               chunks(2), record=False)
        with self.assertRaises(inference_session.SessionError):
            list(call)
        self.assertIsNone(call.first_token_ms, "nothing was dispatched")
        self.assertEqual(lifecycle.leases.get("planner", 0), 0)

    def test_concurrent_streams_share_one_launch(self):
        outcomes = []

        def run():
            call = inference_session.StreamingCall(self.waker, "planner",
                                                   [{"role": "user", "content": "x"}],
                                                   chunks(3), record=False)
            outcomes.append(list(call))
            outcomes.append(call.lease_released)

        threads = [threading.Thread(target=run) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(self.host.launches), 1)
        self.assertTrue(all(outcomes[index] for index in range(1, len(outcomes), 2)))

    def test_the_stream_is_recorded_without_inventing_tokens(self):
        folder = tempfile.TemporaryDirectory()
        original = evidence_record.LOG
        evidence_record.LOG = Path(folder.name) / "records.jsonl"
        try:
            call = inference_session.StreamingCall(self.waker, "planner",
                                                   [{"role": "user", "content": "x"}],
                                                   chunks(2), request_id="stream-1")
            list(call)
            rows = evidence_record.load()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["request_id"], "stream-1")
            self.assertIsNone(rows[0]["tokens"])
        finally:
            evidence_record.LOG = original
            folder.cleanup()


class ObservedFieldsTests(unittest.TestCase):
    def test_the_projection_shows_leases_ownership_and_idle_budget(self):
        import runtime_tree

        host = FakeHost()
        lifecycle = model_lifecycle.Lifecycle(model_lifecycle.load(), host=host)
        lifecycle.ensure("planner")
        lifecycle.acquire("planner")
        view = model_lifecycle.observed(lifecycle)
        tree = runtime_tree.projection(host=host, lifecycle_view=view)
        node = [item for item in tree["nodes"] if item["id"] == "model://planner"][0]
        self.assertEqual(node["fields"]["leases"], 1)
        self.assertTrue(node["fields"]["owned"])
        self.assertEqual(node["fields"]["idle_remaining"], "suspended")

    def test_idle_time_does_not_change_the_digest(self):
        import runtime_tree

        host = FakeHost()
        lifecycle = model_lifecycle.Lifecycle(model_lifecycle.load(), host=host)
        lifecycle.ensure("planner")
        first = runtime_tree.watch(host=host, lifecycle_view=model_lifecycle.observed(lifecycle))
        host.now += 120
        second = runtime_tree.watch(host=host, lifecycle_view=model_lifecycle.observed(lifecycle))
        self.assertEqual(first["digest"], second["digest"],
                         "the remaining idle budget is display state, not semantics")


class AppWiringTests(unittest.TestCase):
    def test_the_app_holds_one_lifecycle_and_sweeps_on_a_tick(self):
        import asyncio

        import chat_app
        import session_log

        session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())

        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                assert app.lifecycle is not None
                with app.lease("planner"):
                    leased = app.lifecycle.leases.get("planner")
                released = app.lifecycle.leases.get("planner")
                app.sweep_idle()
                return leased, released, app.sweeps, app.last_sweep
        leased, released, sweeps, last = asyncio.run(drive())
        self.assertEqual(leased, 1)
        self.assertEqual(released, 0)
        self.assertEqual(sweeps, 1)
        self.assertIn("stopped", last)

    def test_a_lease_is_returned_when_the_body_raises(self):
        import asyncio

        import chat_app
        import session_log

        session_log.SESSIONS_DIR = Path(tempfile.mkdtemp())

        async def drive():
            app = chat_app.ChatApp()
            async with app.run_test(size=(120, 50)) as pilot:
                await pilot.pause()
                try:
                    with app.lease("planner"):
                        raise RuntimeError("the turn failed")
                except RuntimeError:
                    pass
                return app.lifecycle.leases.get("planner")
        self.assertEqual(asyncio.run(drive()), 0)


def _cold_declaration() -> Path:
    import json

    record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "models.json")
                        .read_text(encoding="utf-8"))
    record["models"]["planner"]["startup_timeout_seconds"] = 1
    folder = Path(tempfile.mkdtemp()) / "models.json"
    folder.write_text(json.dumps(record), encoding="utf-8")
    return folder


if __name__ == "__main__":
    unittest.main()
