"""M79: a successful write is not evidence that the intended content changed.

Twice a milestone insert silently no-opped because the anchor was stale and `str.replace` returned the original
text. The writer now asserts the marker appears exactly once and the byte count moved.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plan_edit  # noqa: E402


class MarkerTests(unittest.TestCase):
    def test_a_marker_is_stable_and_machine_checkable(self):
        self.assertEqual(plan_edit.marker_for("M79 write verification"),
                         "<!-- milestone:m79-write-verification -->")
        self.assertEqual(plan_edit.marker_for("m79-write-verification"),
                         "<!-- milestone:m79-write-verification -->")

    def test_an_unusable_identifier_is_refused(self):
        with self.assertRaises(plan_edit.PlanEditError):
            plan_edit.marker_for("   ")


class InsertTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "PLAN.md"
        self.path.write_text("# Ledger\n\n## Existing section\n", encoding="utf-8")

    def tearDown(self):
        self.folder.cleanup()

    def test_a_section_is_inserted_once_and_verified(self):
        report = plan_edit.insert_section(self.path, "first", "body one")
        self.assertTrue(report["inserted"])
        self.assertEqual(report["occurrences"], 1)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn(plan_edit.marker_for("first"), text)
        self.assertIn("body one", text)

    def test_inserting_twice_is_a_no_op_not_a_duplicate(self):
        plan_edit.insert_section(self.path, "first", "body one")
        second = plan_edit.insert_section(self.path, "first", "body one")
        self.assertFalse(second["inserted"])
        self.assertEqual(second["reason"], "the section is already present")
        self.assertEqual(self.path.read_text(encoding="utf-8").count(plan_edit.marker_for("first")), 1)

    def test_a_stale_anchor_still_writes_and_is_verified(self):
        report = plan_edit.insert_section(self.path, "second", "body two",
                                          before="## Anchor that does not exist")
        self.assertTrue(report["inserted"])
        self.assertEqual(report["where"], "appended")
        self.assertGreater(report["size_after"], report["size_before"])

    def test_a_duplicated_marker_before_writing_is_refused(self):
        text = self.path.read_text(encoding="utf-8")
        marker = plan_edit.marker_for("dup")
        self.path.write_text(text + marker + "\nx\n" + marker + "\ny\n", encoding="utf-8")
        with self.assertRaises(plan_edit.PlanEditError):
            plan_edit.insert_section(self.path, "dup", "body")

    def test_the_ledger_ids_are_usable_markers(self):
        for identifier in ("evidence gate", "phase observations", "idle transition"):
            self.assertTrue(plan_edit.marker_for(identifier).startswith("<!-- milestone:"))
