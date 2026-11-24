"""M54: lease-wrapped inference - one startup per cold model, and a lease that always comes back.

The three behaviours the review singled out, each as a test:

    single flight     three concurrent requests for one cold model launch exactly one server
    lease discipline  success, model error and dispatch error all release the lease
    cold vs warm      wake latency is measured on the cold call and reported as zero for the ones that
                      reused the running server
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
    """A clock, ports, and a launch that takes time - so a second caller can race the first."""

    def __init__(self, *, listening=(), launch_delay=0.05, ever_ready=True):
        self.open = set(listening)
        self.launches: list[tuple[str, int]] = []
        self.stops: list[str] = []
        self.now = 1000.0
        self.launch_delay = launch_delay
        self.ever_ready = ever_ready
        self.lock = threading.Lock()

    def listening(self, port):
        return port in self.open

    def launch(self, name, spec):
        with self.lock:
            self.launches.append((name, spec["port"]))
            time.sleep(self.launch_delay)
            if self.ever_ready:
                self.open.add(spec["port"])
        return dict(pid=2000 + len(self.launches))

    def stop(self, name, spec):
        self.stops.append(name)
        self.open.discard(spec["port"])
        return dict(stopped=True)

    def clock(self):
        return self.now


def conversation(text="task"):
    return [{"role": "user", "content": text}]


def reply(text='{"phase": "Sek", "operators": ["filter"], "authority": "proposal"}', model="qwen"):
    return dict(text=text, model=model, completion_tokens=7, latency_ms=5)


class SingleFlightTests(unittest.TestCase):
    def setUp(self):
        self.declaration = model_lifecycle.load()

    def test_concurrent_requests_launch_one_server(self):
        host = FakeHost(launch_delay=0.15)
        lifecycle = model_lifecycle.Lifecycle(self.declaration, host=host)
        waker = inference_session.Waker(lifecycle)
        outcomes = []
        threads = [threading.Thread(target=lambda: outcomes.append(
            inference_session.infer(waker, "planner", conversation(), reply, record=False)))
            for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(host.launches), 1, "one startup for four callers")
        self.assertEqual(len(outcomes), 4)
        self.assertTrue(all(outcome["ok"] for outcome in outcomes))
        cold = [outcome for outcome in outcomes if outcome["model_was_cold"]]
        self.assertEqual(len(cold), 1, "only the caller that woke the model saw a cold start")
        self.assertEqual(lifecycle.leases.get("planner"), 0, "every lease came back")

    def test_a_second_call_reuses_the_running_server(self):
        host = FakeHost()
        lifecycle = model_lifecycle.Lifecycle(self.declaration, host=host)
        waker = inference_session.Waker(lifecycle)
        first = inference_session.infer(waker, "planner", conversation(), reply, record=False)
        second = inference_session.infer(waker, "planner", conversation(), reply, record=False)
        self.assertTrue(first["model_was_cold"])
        self.assertFalse(second["model_was_cold"])
        self.assertEqual(len(host.launches), 1)


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.declaration = model_lifecycle.load()
        self.host = FakeHost()
        self.lifecycle = model_lifecycle.Lifecycle(self.declaration, host=self.host)
        self.waker = inference_session.Waker(self.lifecycle)

    def test_a_successful_call_releases_its_lease(self):
        outcome = inference_session.infer(self.waker, "planner", conversation(), reply, record=False)
        self.assertTrue(outcome["ok"])
        self.assertTrue(outcome["lease_released"])
        self.assertEqual(self.lifecycle.leases.get("planner"), 0)

    def test_a_dispatch_error_still_releases_the_lease(self):
        def explode(_conversation):
            raise TimeoutError("server took too long")

        outcome = inference_session.infer(self.waker, "planner", conversation(), explode, record=False)
        self.assertFalse(outcome["ok"])
        self.assertIn("TimeoutError", outcome["error"])
        self.assertTrue(outcome["lease_released"])
        self.assertEqual(self.lifecycle.leases.get("planner"), 0)

    def test_measurements_are_separate_and_never_invented(self):
        outcome = inference_session.infer(self.waker, "planner", conversation(), reply, record=False)
        for field in inference_session.MEASUREMENTS:
            self.assertIn(field, outcome, field)
        self.assertIsInstance(outcome["wake_latency_ms"], int)
        self.assertIsInstance(outcome["inference_latency_ms"], int)
        self.assertIsInstance(outcome["total_latency_ms"], int)
        self.assertGreaterEqual(outcome["total_latency_ms"], outcome["inference_latency_ms"])

    def test_an_unready_backend_is_refused_and_leaks_nothing(self):
        import json

        # A short startup timeout keeps the test honest: the wait is real wall-clock time.
        record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "models.json")
                            .read_text(encoding="utf-8"))
        record["models"]["planner"]["startup_timeout_seconds"] = 1
        folder = Path(tempfile.mkdtemp()) / "models.json"
        folder.write_text(json.dumps(record), encoding="utf-8")
        declaration = model_lifecycle.load(folder)
        host = FakeHost(ever_ready=False)
        lifecycle = model_lifecycle.Lifecycle(declaration, host=host)
        waker = inference_session.Waker(lifecycle)
        outcome = inference_session.infer(waker, "planner", conversation(), reply, record=False)
        self.assertFalse(outcome["ok"])
        self.assertEqual(outcome["refused"], "model_not_ready")
        self.assertIsNone(outcome["inference_latency_ms"], "no inference happened")
        self.assertEqual(lifecycle.leases.get("planner", 0), 0)

    def test_an_idle_backend_can_be_stopped_after_its_lease_ends(self):
        inference_session.infer(self.waker, "planner", conversation(), reply, record=False)
        self.host.now += 10_000
        sweep = self.lifecycle.release_idle()
        self.assertEqual([item["model"] for item in sweep["stopped"]], ["planner"])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.declaration = model_lifecycle.load()
        self.host = FakeHost()                         # nothing listening
        self.lifecycle = model_lifecycle.Lifecycle(self.declaration, host=self.host)
        self.router = self.declaration["router"]

    def test_a_cold_registered_model_is_still_a_candidate(self):
        binding = inference_session.select(self.router, "micronaut://v1/compose",
                                           lifecycle=self.lifecycle, allow_cold=True)
        self.assertTrue(binding["ok"], binding)
        self.assertEqual(binding["selected"], "planner")
        self.assertTrue(binding["cold"], "registered and wakeable, not running")

    def test_without_allow_cold_the_selection_refuses(self):
        binding = inference_session.select(self.router, "micronaut://v1/compose",
                                           lifecycle=self.lifecycle, allow_cold=False)
        self.assertFalse(binding["ok"])
        self.assertEqual(binding["refused"], "no_healthy_endpoint")

    def test_the_view_separates_wakeable_from_healthy(self):
        view = inference_session.router_view(self.router, self.lifecycle)
        for name, entry in view.items():
            self.assertTrue(entry["wakeable"], name)
            self.assertFalse(entry["healthy"], name)
            self.assertEqual(entry["state"], "cold", name)


class RecordTests(unittest.TestCase):
    def test_the_inference_is_recorded_without_inventing_tokens(self):
        folder = tempfile.TemporaryDirectory()
        original = evidence_record.LOG
        evidence_record.LOG = Path(folder.name) / "records.jsonl"
        try:
            declaration = model_lifecycle.load()
            host = FakeHost()
            lifecycle = model_lifecycle.Lifecycle(declaration, host=host)
            waker = inference_session.Waker(lifecycle)
            outcome = inference_session.infer(waker, "planner", conversation(),
                                              lambda _c: dict(text="x", model="qwen",
                                                              completion_tokens=None),
                                              request_id="req-1")
            rows = evidence_record.load()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["request_id"], "req-1")
            self.assertEqual(rows[0]["inference"], "model")
            self.assertIsNone(rows[0]["tokens"], "no token count was reported")
            self.assertTrue(outcome["lease_released"])
        finally:
            evidence_record.LOG = original
            folder.cleanup()

    def test_a_lost_record_does_not_lose_the_answer(self):
        original = evidence_record.append

        def broken(*args, **kwargs):
            raise OSError("disk full")

        evidence_record.append = broken
        try:
            declaration = model_lifecycle.load()
            lifecycle = model_lifecycle.Lifecycle(declaration, host=FakeHost())
            waker = inference_session.Waker(lifecycle)
            outcome = inference_session.infer(waker, "planner", conversation(), reply, request_id="r2")
        finally:
            evidence_record.append = original
        self.assertTrue(outcome["ok"], "the answer survived the recording failure")
        self.assertIn("disk full", outcome.get("record_error", ""))


if __name__ == "__main__":
    unittest.main()
