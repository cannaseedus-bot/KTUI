"""M10: the optional audit ledger keeps its promises, and keeps them honest.

  chain    - records link by hash; a new record refuses to append to a broken chain
  tamper   - editing a record, deleting one, or reordering them is detected at a named index
  canonical- serialization is byte-stable regardless of dict insertion order, and floats are refused
  signing  - Ed25519 signatures verify, a wrong key fails, and an unsigned ledger says it is unsigned
  shape    - ledger.gml is the declared record shape, and the plugin reads it
  authority- recording a gate verdict never grants merge permission
"""
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

import ledger_plugin  # noqa: E402


def fresh(folder, name="audit.jsonl"):
    return Path(folder) / name


class M10AuditLedger(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = fresh(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    # chain
    def test_appends_link_and_verify(self):
        first = ledger_plugin.append({"kind": "event", "payload": {"n": 1}}, self.path)
        second = ledger_plugin.append({"kind": "event", "payload": {"n": 2}}, self.path)
        self.assertEqual(first["sequence"], 0)
        self.assertEqual(first["previous_hash"], ledger_plugin.GENESIS)
        self.assertEqual(second["previous_hash"], first["content_hash"])
        report = ledger_plugin.verify(self.path)
        self.assertTrue(report["ok"], report["reasons"])
        self.assertEqual(report["entries"], 2)

    def test_append_refuses_a_broken_chain(self):
        ledger_plugin.append({"kind": "event", "payload": {"n": 1}}, self.path)
        lines = self.path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["payload"]["n"] = 99
        self.path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ledger_plugin.LedgerError, "does not verify"):
            ledger_plugin.append({"kind": "event", "payload": {"n": 2}}, self.path)

    # tamper
    def test_edited_record_is_detected(self):
        ledger_plugin.append({"kind": "event", "payload": {"amount": 1}}, self.path)
        ledger_plugin.append({"kind": "event", "payload": {"amount": 2}}, self.path)
        lines = self.path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[1])
        record["payload"]["amount"] = 1000
        lines[1] = json.dumps(record)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = ledger_plugin.verify(self.path)
        self.assertFalse(report["ok"])
        self.assertEqual(report["reasons"][0]["code"], "content_mismatch")
        self.assertEqual(report["reasons"][0]["index"], 1)

    def test_deleted_record_is_detected(self):
        for value in (1, 2, 3):
            ledger_plugin.append({"kind": "event", "payload": {"n": value}}, self.path)
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
        report = ledger_plugin.verify(self.path)
        self.assertFalse(report["ok"])
        codes = [reason["code"] for reason in report["reasons"]]
        self.assertIn("sequence_gap", codes)
        self.assertIn("broken_link", codes)

    def test_reordered_records_are_detected(self):
        for value in (1, 2):
            ledger_plugin.append({"kind": "event", "payload": {"n": value}}, self.path)
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.path.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
        self.assertFalse(ledger_plugin.verify(self.path)["ok"])

    # canonical
    def test_canonical_is_order_independent(self):
        left = {"b": 2, "a": {"y": 1, "x": [1, 2]}}
        right = {"a": {"x": [1, 2], "y": 1}, "b": 2}
        self.assertEqual(ledger_plugin.canonical(left), ledger_plugin.canonical(right))

    def test_floats_are_refused(self):
        with self.assertRaisesRegex(ledger_plugin.LedgerError, "float"):
            ledger_plugin.append({"kind": "event", "payload": {"amount": 1.5}}, self.path)

    # signing
    def test_signed_records_verify_and_unsigned_records_say_so(self):
        availability = ledger_plugin.available()
        ledger_plugin.append({"kind": "event", "payload": {"n": 1}}, self.path)
        unsigned = ledger_plugin.verify(self.path)
        self.assertEqual(unsigned["signed"], 0)
        self.assertEqual(unsigned["unsigned"], 1)
        if not availability["signatures"]:
            self.skipTest(f"no signature backend: {availability['reason']}")
        key = Path(self.folder.name) / "key.pem"
        ledger_plugin.append({"kind": "event", "payload": {"n": 2}}, self.path,
                             key_path=key, create_key=True)
        signed = ledger_plugin.verify(self.path)
        self.assertTrue(signed["ok"], signed["reasons"])
        self.assertEqual(signed["signed"], 1)
        self.assertIn("ed25519", signed["algorithm"])

    def test_wrong_key_fails_verification(self):
        if not ledger_plugin.available()["signatures"]:
            self.skipTest("no signature backend")
        key = Path(self.folder.name) / "key.pem"
        ledger_plugin.append({"kind": "event", "payload": {"n": 1}}, self.path,
                             key_path=key, create_key=True)
        other = Path(self.folder.name) / "other.pem"
        other_key = ledger_plugin.load_key(other, create=True)
        self.assertFalse(ledger_plugin.verify(self.path,
                                              public_hex=ledger_plugin.public_bytes(other_key))["ok"])

    # shape
    def test_ledger_gml_declares_the_record_shape(self):
        fields, source = ledger_plugin.schema_fields()
        self.assertEqual(source, "ledger.gml")
        for name in ("sequence", "previous_hash", "content_hash", "kind", "payload", "signature"):
            self.assertIn(name, fields)

    # authority
    def test_recording_a_verdict_grants_nothing(self):
        report = {"verdict": {"tested_commit": "a" * 40, "evidence_satisfied": True,
                             "merge_authorized": True, "authority": "human",
                             "ledgers": {"F14": {"state": "closed"}}},
                  "comparability": {"informational": [{"code": "baseline_partial"}]}}
        record = ledger_plugin.record_gate_report(report, self.path)
        self.assertFalse(record["payload"]["merge_authorized"],
                         "a ledger record must never carry merge authority, whatever the input says")
        self.assertTrue(record["payload"]["evidence_satisfied"])
        self.assertEqual(ledger_plugin.verify(self.path)["entries"], 1)


if __name__ == "__main__":
    unittest.main()
