"""M48: inference on demand - a registered wake, owned stops, and leases that keep a shared backend up.

The rules the review asked for, as tests:

    only a registered launcher runs        an alias and a port from the manifest; a proposal cannot
                                           supply a command, and a `launch.command` field is refused
    only an owned process is stopped       ownership is the pid this lifecycle started, on the declared port
    never stop while a lease is held       several micronauts share one backend, so a stop needs zero leases
    never stop before the idle timer       a released lease restarts the timer, it does not stop anything

The host is injected in every test, so no server is spawned and no port is touched.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import model_lifecycle  # noqa: E402


class FakeHost:
    """A clock, a port table and a launch/stop recorder - nothing real."""

    def __init__(self, *, listening=(9040,), now=1000.0):
        self.open_ports = set(listening)
        self.now = now
        self.launches = []
        self.stops = []
        self.fail_to_open = set()

    def listening(self, port):
        return port in self.open_ports

    def launch(self, name, spec):
        self.launches.append((name, dict(spec)))
        if spec["port"] not in self.fail_to_open:
            self.open_ports.add(spec["port"])
        return dict(pid=1000 + len(self.launches), model=name)

    def stop(self, name, spec):
        self.stops.append((name, dict(spec)))
        self.open_ports.discard(spec["port"])
        return dict(port=spec["port"], stopped=True, stopped_pids=[1000])

    def clock(self):
        return self.now


def declaration_with(overrides: dict) -> dict:
    record = json.loads((ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "models.json")
                       .read_text(encoding="utf-8"))
    for name, patch in overrides.items():
        record["models"][name].update(patch)
    folder = Path(tempfile.mkdtemp()) / "models.json"
    folder.write_text(json.dumps(record), encoding="utf-8")
    return model_lifecycle.load(folder)


class DeclarationTests(unittest.TestCase):
    def test_the_shipped_declaration_is_valid(self):
        declaration = model_lifecycle.load()
        self.assertTrue(declaration["ok"], declaration["problems"])
        for name, entry in declaration["by_name"].items():
            self.assertIn(entry["state"], ("hot", "cold"), name)
            self.assertIsInstance(entry["launch"]["port"], int, name)
            self.assertTrue(entry["launch"]["alias"], name)

    def test_a_command_field_is_refused(self):
        declaration = declaration_with({"advisor": {"launch": {"alias": "gpt-oss-20b", "port": 9032,
                                                              "command": "rm -rf /"}}})
        self.assertFalse(declaration["ok"])
        self.assertIn("launch_command", [problem["code"] for problem in declaration["problems"]])

    def test_a_model_without_a_launch_alias_is_not_wakeable(self):
        declaration = declaration_with({"planner": {"launch": {"port": 9041}}})
        self.assertFalse(declaration["ok"])
        self.assertIn("launch", [problem["code"] for problem in declaration["problems"]])


class StateTests(unittest.TestCase):
    def setUp(self):
        self.declaration = model_lifecycle.load()

    def test_a_listening_port_is_hot(self):
        host = FakeHost(listening=(9040,))
        self.assertEqual(model_lifecycle.state(self.declaration, "worker", host=host)["state"], "hot")

    def test_a_closed_port_is_cold(self):
        host = FakeHost(listening=())
        self.assertEqual(model_lifecycle.state(self.declaration, "advisor", host=host)["state"], "cold")

    def test_warm_is_declared_unsupported_rather_than_faked(self):
        host = FakeHost(listening=())
        result = model_lifecycle.state(self.declaration, "advisor", host=host)
        self.assertIn("warm", result["note"])
        self.assertEqual(result["state"], "cold")

    def test_an_unregistered_model_has_no_state(self):
        result = model_lifecycle.state(self.declaration, "ghost", host=FakeHost())
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["refused"], "model_not_registered")


class WakeTests(unittest.TestCase):
    def setUp(self):
        self.declaration = model_lifecycle.load()

    def test_a_hot_backend_is_not_relaunched(self):
        host = FakeHost(listening=(9040,))
        lifecycle = model_lifecycle.Lifecycle(self.declaration, host=host)
        result = lifecycle.ensure("worker")
        self.assertTrue(result["state"] == "hot")
        self.assertFalse(result["started"])
        self.assertEqual(host.launches, [])

    def test_a_cold_backend_is_woken_by_the_registered_launch(self):
        host = FakeHost(listening=())
        lifecycle = model_lifecycle.Lifecycle(self.declaration, host=host)
        result = lifecycle.ensure("planner")
        self.assertTrue(result["started"])
        self.assertEqual(result["state"], "hot")
        self.assertEqual(len(host.launches), 1)
        launched = host.launches[0][1]
        self.assertEqual(launched["port"], 9041)
        self.assertEqual(launched["alias"], "qwen3-1.7b-q4")

    def test_an_unregistered_model_cannot_be_woken(self):
        lifecycle = model_lifecycle.Lifecycle(self.declaration, host=FakeHost())
        with self.assertRaises(model_lifecycle.LifecycleError):
            lifecycle.ensure("ghost")


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.declaration = model_lifecycle.load()

    def test_a_leased_backend_does_not_sleep(self):
        host = FakeHost(listening=())
        lifecycle = model_lifecycle.Lifecycle(self.declaration, host=host)
        lifecycle.ensure("worker")
        lifecycle.acquire("worker")                 # one micronaut is still using it
        host.now += 10_000
        outcome = lifecycle.release_idle()
        self.assertEqual(outcome["stopped"], [])
        self.assertEqual(host.stops, [])
        self.assertIn({"model": "worker", "reason": "leased"}, outcome["kept"])

    def test_the_last_release_then_the_idle_timer_stops_it(self):
        host = FakeHost(listening=())
        lifecycle = model_lifecycle.Lifecycle(self.declaration, host=host)
        lifecycle.ensure("worker")
        lifecycle.acquire("worker")
        lifecycle.release("worker")
        host.now += 10_000                          # past worker's 900s timeout
        outcome = lifecycle.release_idle()
        self.assertEqual([item["model"] for item in outcome["stopped"]], ["worker"])
        self.assertEqual([name for name, _ in host.stops], ["worker"])

    def test_an_unowned_process_is_never_stopped(self):
        host = FakeHost(listening=())
        lifecycle = model_lifecycle.Lifecycle(self.declaration, host=host)
        # advisor is listening because something else started it: not owned, so not ours to stop
        host.open_ports.add(9032)
        host.now += 10_000
        outcome = lifecycle.release_idle()
        self.assertEqual(outcome["stopped"], [])
        self.assertEqual(host.stops, [])

    def test_a_not_yet_idle_backend_is_kept(self):
        host = FakeHost(listening=())
        lifecycle = model_lifecycle.Lifecycle(self.declaration, host=host)
        lifecycle.ensure("worker")
        host.now += 5
        outcome = lifecycle.release_idle()
        self.assertEqual(outcome["stopped"], [])
        self.assertEqual(outcome["kept"][0]["reason"], "not_idle")

    def test_releasing_without_a_lease_is_an_error(self):
        lifecycle = model_lifecycle.Lifecycle(self.declaration, host=FakeHost())
        with self.assertRaises(model_lifecycle.LifecycleError):
            lifecycle.release("worker")


class BackendDiagnosisTests(unittest.TestCase):
    """An unmatched model name must be reported, not silently streamed unmanaged."""

    @classmethod
    def setUpClass(cls):
        cls.declaration = model_lifecycle.load()

    def test_a_declared_alias_matches(self):
        report = model_lifecycle.diagnose_backend(self.declaration, "gpt-oss-20b")
        self.assertTrue(report["matched"])
        self.assertEqual(report["backend"], "advisor")
        self.assertIsNone(report["reason"])

    def test_a_served_file_name_matches_its_alias(self):
        report = model_lifecycle.diagnose_backend(
            self.declaration, "C:/Users/canna/.models/gpt-oss-20b-MXFP4.gguf")
        self.assertTrue(report["matched"], "llama-server reports its own file name")
        self.assertEqual(report["backend"], "advisor")

    def test_an_unknown_model_is_named_as_unmanaged(self):
        report = model_lifecycle.diagnose_backend(self.declaration, "mystery-7b")
        self.assertFalse(report["matched"])
        self.assertIn("unmanaged_backend", report["reason"])


class TransitionObservationTests(unittest.TestCase):
    """The committed observation must show a stop the sweep performed, not one that happened by itself."""

    def test_the_observation_recorded_an_idle_stop(self):
        import json

        artifact = ROOT / "kuhul-phase-engine-v0.1.0" / "data" / "lifecycle-transition.json"
        if not artifact.is_file():
            self.skipTest("no transition observation recorded yet")
        report = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertTrue(report.get("ok"), report.get("refused"))
        self.assertTrue(report.get("sweep_stopped_it"),
                        "a cold state after the server exited by itself is not the sweep working")
        self.assertFalse(report.get("already_stopped"))
        stopped = [item for item in report["stopped"] if item.get("reason") == "idle"]
        self.assertEqual(len(stopped), 1)
        self.assertEqual(report["before_states"], "cold")
        self.assertEqual(report["after_state"], "cold")
        steps = {step["step"]: step for step in report["steps"]}
        self.assertEqual(steps["sweep_while_leased"]["stopped"], [])
        self.assertIn("leased", [item["reason"] for item in steps["sweep_while_leased"]["kept"]])


if __name__ == "__main__":
    unittest.main()
