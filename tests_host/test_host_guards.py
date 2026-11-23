"""Host-side guards M3-M7: the invariants that keep the integration honest after a merge.

These run against the *host* (this repository), not the K'UHUL package:

  M3  extension_contract() reads the GML document; editing the document changes the contract
  M4  every expected gml_* function is registered, has a handler, and answers a representative call
  M5  the package suite is green *after* integration, not merely before
  M6  the -text preservation rule survives, so manifest digests stay valid
  M7  PLAN.md's ledger is mirrored into task-list.json and agrees with it

Run with:  python -m unittest discover -s tests_host -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import functions  # noqa: E402
import phases  # noqa: E402
import planner  # noqa: E402
import mirror_ledger  # noqa: E402
import task_list  # noqa: E402

PACKAGE = ROOT / "kuhul-phase-engine-v0.1.0"


def context():
    return functions.ToolContext(ROOT)


class M3RegistryDocumentIsTheSourceOfTruth(unittest.TestCase):
    def test_contract_reads_the_real_document(self):
        contract = phases.extension_contract()
        self.assertEqual(contract["schema_id"], "gml-tensor/1")
        self.assertGreaterEqual(len(contract["fields"]), 19)
        self.assertTrue(any(field.get("name") == "dtype" for field in contract["fields"]))
        names = {rule.get("name") for rule in contract["constraints"]}
        self.assertIn("dtype_match", names)

    def test_editing_the_document_changes_the_contract(self):
        """If this fails, the contract is being read from Python instead of the registry file."""
        source = (PACKAGE / "schemas" / "tensor-registry.gml").read_text(encoding="utf-8")
        edited = source.replace(
            'field [ path "slice" name "col_offset" type "nonnegative_integer" required 1 ]',
            'field [ path "slice" name "col_offset" type "nonnegative_integer" required 1 ]\n'
            '  field [ path "slice" name "row_stride" type "positive_integer" required 0 ]', 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tensor-registry.gml"
            path.write_text(edited, encoding="utf-8")
            contract = phases.extension_contract(path)
        self.assertEqual(len(contract["fields"]), len(phases.extension_contract()["fields"]) + 1)
        self.assertIn("row_stride", json.dumps(contract["fields"]))


class M4GmlFunctionsAreRegistered(unittest.TestCase):
    EXPECTED = ("gml_registry", "gml_validate", "gml_assemble")

    def test_every_expected_function_is_registered_with_a_handler(self):
        for name in self.EXPECTED:
            entry = functions.get(name)
            self.assertIsNotNone(entry, f"{name} is not registered")
            self.assertIsNotNone(entry.handler, f"{name} has no handler")
            self.assertTrue(any(form.startswith(name + "(") for form in functions.declarations()),
                            f"{name} is registered but absent from declarations()")

    def test_representative_calls_answer(self):
        registry_text = functions.get("gml_registry").handler(context())
        self.assertIn("gml-tensor/1", registry_text)

        rows = functions.get("gml_validate").handler(
            context(), [{"path": "kuhul-phase-engine-v0.1.0/contracts/col_a.gml"},
                        {"path": "kuhul-phase-engine-v0.1.0/contracts/category.gml"}])
        states = {row["file"].split("/")[-1]: row["state"] for row in rows}
        self.assertEqual(states["col_a.gml"], "STRUCTURALLY_VALIDATED")
        self.assertEqual(states["category.gml"], "OUT_OF_SCOPE")

        assembled = functions.get("gml_assemble").handler(context())
        self.assertIn("tensor/assembled", assembled)
        self.assertIn("plan only", assembled)

    def test_the_gml_plan_still_admits_and_runs(self):
        plan = planner.resolve("gml_audit")
        self.assertTrue(plan.admitted, plan.problems)
        ok, text = planner.run(plan, context())
        self.assertTrue(ok, text)
        self.assertIn("STRUCTURALLY_VALIDATED", text)


class M5PackageSuiteIsGreenAfterIntegration(unittest.TestCase):
    def test_package_suite_green(self):
        """M5 is about the state after integration, so it is checked here, every run."""
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                                cwd=PACKAGE, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=300)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output[-1500:])
        self.assertRegex(output, r"Ran (\d+) tests?")
        self.assertIn("OK", output)
        self.assertNotIn("FAILED", output)


class M6TextRuleKeepsTheDigestsValid(unittest.TestCase):
    def test_gitattributes_keeps_the_package_raw(self):
        result = subprocess.run(["git", "check-attr", "text", "--",
                                 "kuhul-phase-engine-v0.1.0/phases/pop.aiml"],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("text: unset", result.stdout)
        self.assertIn("phases/pop.aiml", result.stdout)

    def test_manifest_digests_still_verify(self):
        report = phases.verify()
        self.assertEqual(report["bad_digest"], [])
        self.assertEqual(len(report["banks"]), 9)
        self.assertTrue(all(phases.trusted(path) for _, path in phases.load_order()
                            if path.name.endswith(".aiml")))


class M7LedgerMirrorsIntoTheTaskList(unittest.TestCase):
    def test_mirror_agrees_with_the_ledger(self):
        rows = mirror_ledger.ledger_rows()
        self.assertTrue(rows, "PLAN.md has no ledger rows")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "task-list.json"
            task_list.save({"tasks": [{"id": "human1", "title": "a human task", "status": "doing",
                                       "priority": "low", "note": "", "created_at": "x",
                                       "updated_at": "x"}]}, path)
            self.assertEqual(mirror_ledger.main([str(path)]), 0)
            document = task_list.load(path)
            before = json.dumps(document, sort_keys=True)
            self.assertEqual(mirror_ledger.main([str(path)]), 0)
            self.assertEqual(json.dumps(task_list.load(path), sort_keys=True), before,
                             "the mirror is not idempotent")
        titles = {task["title"].split(" — ")[0]: task for task in document["tasks"]
                  if " — " in task["title"]}
        for row in rows:
            self.assertIn(row["id"], titles, f"{row['id']} missing from the mirror")
            expected = mirror_ledger.STATUS[row["status"]]
            self.assertEqual(titles[row["id"]]["status"], expected, row["id"])
            self.assertIn("ledger:", titles[row["id"]]["note"])
        self.assertIn("a human task", [task["title"] for task in document["tasks"]])


if __name__ == "__main__":
    unittest.main()
