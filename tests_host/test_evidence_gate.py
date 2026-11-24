"""M72: the evidence gate proves all three suites, not just the one it happened to run.

The regression this repairs: `evidence_satisfied: true` was reported while only the **package** suite had
executed. The gate now demands, per required suite: executed, passed, counted (at least its minimum), at the
tested commit, with a clean tree - and names whichever term is missing.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evidence_gate  # noqa: E402

PASS = dict(package=(139, 0), harness=(14, 0), host_guards=(627, 0))


def runner_for(counts):
    def runner(name, command, cwd):
        if name not in counts:
            raise AssertionError(f"the gate asked for {name}, which this fixture does not provide")
        tests, exit_code = counts[name]
        status = "OK" if exit_code == 0 else "FAILED (failures=2)"
        return dict(output=f"Ran {tests} tests in 1s\n\n{status}", exit_code=exit_code)
    return runner


class ManifestTests(unittest.TestCase):
    def test_the_manifest_declares_three_required_suites(self):
        manifest = evidence_gate.load()
        self.assertTrue(manifest["ok"], manifest["problems"])
        self.assertEqual(manifest["required"], ["package", "harness", "host_guards"])
        for name in manifest["required"]:
            self.assertTrue(manifest["suites"][name]["command"], name)
            self.assertIsInstance(manifest["suites"][name]["minimum_tests"], int, name)

    def test_a_manifest_without_a_command_is_refused(self):
        record = json.loads((ROOT / "evidence-suites.json").read_text(encoding="utf-8"))
        del record["suites"]["harness"]["command"]
        folder = Path(tempfile.mkdtemp()) / "suites.json"
        folder.write_text(json.dumps(record), encoding="utf-8")
        report = evidence_gate.load(folder)
        self.assertFalse(report["ok"])
        self.assertIn("command", [problem["code"] for problem in report["problems"]])


class VerdictTests(unittest.TestCase):
    def test_all_three_passing_is_satisfied(self):
        record = evidence_gate.capture(runner=runner_for(PASS), head="abc", captured_clean=True)
        self.assertTrue(record["verdict"]["evidence_satisfied"], record["verdict"]["problems"])
        self.assertEqual(record["verdict"]["passed"], ["package", "harness", "host_guards"])
        self.assertFalse(record["verdict"]["merge_authorized"])

    def test_a_failing_host_guard_suite_is_not_satisfied(self):
        counts = dict(PASS, host_guards=(627, 1))
        record = evidence_gate.capture(runner=runner_for(counts), head="abc", captured_clean=True)
        verdict = record["verdict"]
        self.assertFalse(verdict["evidence_satisfied"])
        self.assertIn("suite_failed", [problem["code"] for problem in verdict["problems"]])
        self.assertNotIn("host_guards", verdict["passed"])
        self.assertIn("host_guards", verdict["executed"], "it ran; it failed")

    def test_a_missing_suite_is_not_a_pass(self):
        counts = {name: value for name, value in PASS.items() if name != "host_guards"}
        record = evidence_gate.capture(runner=runner_for(counts), head="abc", captured_clean=True)
        codes = [problem["code"] for problem in record["verdict"]["problems"]]
        self.assertFalse(record["verdict"]["evidence_satisfied"])
        self.assertIn("suite_not_executed", codes)

    def test_a_short_suite_is_incomplete(self):
        counts = dict(PASS, host_guards=(3, 0))
        record = evidence_gate.capture(runner=runner_for(counts), head="abc", captured_clean=True)
        verdict = record["verdict"]
        self.assertFalse(verdict["evidence_satisfied"])
        self.assertIn("suite_incomplete", [problem["code"] for problem in verdict["problems"]])

    def test_a_dirty_tree_blocks_the_evidence(self):
        record = evidence_gate.capture(runner=runner_for(PASS), head="abc", captured_clean=False)
        self.assertFalse(record["verdict"]["evidence_satisfied"])
        self.assertIn("dirty_tree", [problem["code"] for problem in record["verdict"]["problems"]])

    def test_stale_evidence_is_named(self):
        verdict = evidence_gate.verdict(
            {name: dict(executed=True, ok=True, exit_code=0, tests=tests, enough_tests=True)
             for name, (tests, _) in PASS.items()},
            required=["package", "harness", "host_guards"], tested_commit="aaa",
            head="bbb", captured_clean=True)
        self.assertFalse(verdict["evidence_satisfied"])
        self.assertIn("stale_evidence", [problem["code"] for problem in verdict["problems"]])

    def test_one_runner_cannot_stand_in_for_another(self):
        # a green package run with no host-guard execution must never satisfy the gate
        results = {"package": dict(executed=True, ok=True, exit_code=0, tests=139, enough_tests=True)}
        verdict = evidence_gate.verdict(results, required=["package", "harness", "host_guards"],
                                        tested_commit="abc", head="abc", captured_clean=True)
        self.assertFalse(verdict["evidence_satisfied"])
        missing = [problem["detail"] for problem in verdict["problems"]
                   if problem["code"] == "suite_not_executed"]
        self.assertEqual(sorted(missing), ["harness", "host_guards"])

    def test_the_statement_says_what_is_missing(self):
        counts = dict(PASS, harness=(14, 1))
        record = evidence_gate.capture(runner=runner_for(counts), head="abc", captured_clean=True)
        self.assertIn("NOT satisfied", record["verdict"]["statement"])
        self.assertIn("suite_failed", record["verdict"]["statement"])


class ParseTests(unittest.TestCase):
    def test_a_summary_is_read_or_treated_as_failure(self):
        self.assertEqual(evidence_gate.parse("Ran 12 tests in 0.1s\n\nOK")["tests"], 12)
        self.assertTrue(evidence_gate.parse("Ran 12 tests in 0.1s\n\nOK")["ok"])
        self.assertFalse(evidence_gate.parse("something unusual")["ok"])

    def test_a_crash_is_recorded_not_raised(self):
        def crash(name, command, cwd):
            raise OSError("cannot start the runner")

        record = evidence_gate.capture(runner=crash, head="abc", captured_clean=True)
        for result in record["suites"].values():
            self.assertFalse(result["ok"])
        self.assertFalse(record["verdict"]["evidence_satisfied"])


if __name__ == "__main__":
    unittest.main()
