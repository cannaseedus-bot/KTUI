"""M11: the backup is independent, verified, and actually restorable.

A backup that has never been restored is a hope, so these tests do the restoring:

  create+restore  - a bundle of every ref restores to the same commit, with the suites green in the clone
  manifest        - each bundle's SHA-256 is recorded, and a tampered bundle is reported, not ignored
  ledger          - the backup is recorded in the audit ledger as a chained entry
  missing         - a backup that is gone is reported as gone, never silently "fine"
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backup  # noqa: E402
import ledger_plugin  # noqa: E402


def git(args, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


class M11IndependentBackup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.dest = Path(cls.folder.name) / "backups"
        cls.ledger = Path(cls.folder.name) / "audit.jsonl"
        cls.created = backup.create(cls.dest, ledger=True, ledger_path=cls.ledger)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_create_records_a_bundle_and_manifest(self):
        bundle = Path(self.created["path"])
        manifest = json.loads(Path(self.created["manifest"]).read_text(encoding="utf-8"))
        self.assertTrue(bundle.is_file())
        self.assertEqual(manifest["backups"][-1]["bundle"], bundle.name)
        self.assertEqual(len(manifest["backups"][-1]["sha256"]), 64)
        self.assertGreater(manifest["backups"][-1]["refs"], 0)

    def test_restore_returns_the_same_commit_and_the_suites_run(self):
        """Cloning the bundle must reproduce the commit, and the restored tree must pass its suites."""
        report = backup.verify(Path(self.created["path"]),
                               expect_commit=self.created["entry"]["head"], run_suites=True)
        self.assertTrue(report["ok"], report["reasons"])
        self.assertEqual(report["restored_head"], self.created["entry"]["head"])
        self.assertGreater(report["commits"], 0)
        self.assertTrue(report["suites"]["package"]["ok"], report["suites"]["package"])
        self.assertTrue(report["suites"]["host"]["ok"], report["suites"]["host"])

    def test_tampered_bundle_is_reported(self):
        copied = Path(self.folder.name) / "tampered"
        shutil.copytree(self.dest, copied)
        entry = json.loads((copied / "manifest.json").read_text(encoding="utf-8"))["backups"][-1]
        target = copied / entry["bundle"]
        data = bytearray(target.read_bytes())
        data[len(data) // 2] ^= 0xFF
        target.write_bytes(bytes(data))
        report = backup.verify_latest(copied)
        self.assertFalse(report["ok"])
        self.assertFalse(report["manifest_digest_ok"])

    def test_backup_is_recorded_in_the_ledger(self):
        report = ledger_plugin.verify(self.ledger)
        self.assertTrue(report["ok"], report["reasons"])
        self.assertGreaterEqual(report["entries"], 1)
        last = ledger_plugin.head(self.ledger)
        self.assertEqual(last["kind"], "backup")
        self.assertEqual(last["payload"]["head"], self.created["entry"]["head"])

    def test_missing_backup_is_reported(self):
        report = backup.verify(Path(self.folder.name) / "not-there.bundle")
        self.assertFalse(report["ok"])
        self.assertEqual(report["reasons"][0]["code"], "missing")


if __name__ == "__main__":
    unittest.main()
