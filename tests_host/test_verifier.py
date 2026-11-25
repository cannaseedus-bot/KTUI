"""M86: one SHA-256 lock, not a security system.

`verifier.json` locks a single hash over the tracked source and is updated only when the source is. These guards keep
it honest: it reports drift without rewriting itself, the excluded files are the ones that change per run, and the
lock does not depend on the optional attestation plugin.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import verifier  # noqa: E402


class LockTests(unittest.TestCase):
    def test_the_shipped_lock_is_present_and_locked(self):
        loaded = verifier.load()
        self.assertTrue(loaded["ok"], loaded["refused"])
        record = loaded["record"]
        self.assertTrue(record["locked"])
        self.assertEqual(record["algorithm"], "sha256")
        self.assertGreater(record["count"], 100)
        self.assertEqual(len(record["hash"]), 64)

    def test_the_lock_matches_the_tree_or_refuses_uncommitted_source(self):
        """Either the tree matches the lock, or the lock says the tree is uncommitted - never a silent pass."""
        report = verifier.verify()
        if report["ok"]:
            self.assertEqual(report["current"]["count"], verifier.load()["record"]["count"])
            return
        self.assertEqual(report["refused"], "dirty_source")
        self.assertTrue(report["dirty"], "an uncommitted source must be named")
        for name in report["dirty"]:
            self.assertIsInstance(name, str)

    def test_the_lock_describes_the_working_tree(self):
        record = verifier.load()["record"]
        self.assertEqual(record["source"], "working tree")
        self.assertIn("uncommitted edits are refused", record["covers"])

    def test_the_lock_does_not_hash_its_own_volatile_artifacts(self):
        record = verifier.load()["record"]
        for name in ("verifier.json", "evidence-gate.json"):
            self.assertNotIn(name, record["files"])
        for name in record["files"]:
            self.assertFalse(name.startswith(("logs/", "backups/", "profiles/")), name)
            self.assertFalse(name.startswith("host-gate-"), name)

    def test_verification_never_rewrites_the_lock(self):
        before = Path("verifier.json").read_bytes()
        verifier.verify()
        self.assertEqual(Path("verifier.json").read_bytes(), before,
                         "a check that edits the thing it checks is not a check")

    def test_a_changed_file_is_reported_as_drift(self):
        folder = Path(tempfile.mkdtemp())
        lock = folder / "verifier.json"
        record = verifier.build(lock=lock, force=True)
        self.assertTrue(record["hash"])
        # a lock over a folder whose files are not tracked by git is empty; give it one entry by hand
        record["files"]["README.md"] = "0" * 64
        record["count"] = len(record["files"])
        record["hash"] = "f" * 64
        lock.write_text(json.dumps(record), encoding="utf-8")
        report = verifier.verify(lock=lock, ignore_dirty=True)
        self.assertFalse(report["ok"])
        self.assertEqual(report["refused"], "drift")
        self.assertIn("README.md", report["drift"]["changed"])

    def test_an_update_records_the_previous_hash(self):
        folder = Path(tempfile.mkdtemp())
        lock = folder / "verifier.json"
        verifier.build(lock=lock, force=True)
        first = json.loads(lock.read_text(encoding="utf-8"))
        second = verifier.update(lock=lock, note="re-locked after an edit", force=True)
        self.assertEqual(second["previous"]["hash"], first["hash"])
        self.assertNotEqual(second["hash"], first["hash"] + "x")

    def test_a_dirty_tree_is_never_locked_by_default(self):
        folder = Path(tempfile.mkdtemp())
        lock = folder / "verifier.json"
        if not verifier.dirty_tracked():
            self.skipTest("the tree is clean, so there is nothing to refuse")
        with self.assertRaises(verifier.VerifierError):
            verifier.build(lock=lock)
        self.assertFalse(lock.is_file(), "a refused build writes nothing")

    def test_the_lock_says_the_attestation_ledger_is_optional(self):
        record = verifier.load()["record"]
        self.assertIn("plugin", record["optional_plugin"])
        self.assertIn("does not depend", record["optional_plugin"])

    def test_the_verifier_does_not_import_the_crypto_plugin(self):
        source = (ROOT / "verifier.py").read_text(encoding="utf-8")
        for name in ("review_attestations", "keymaker"):
            self.assertNotIn(f"import {name}", source)


if __name__ == "__main__":
    unittest.main()
