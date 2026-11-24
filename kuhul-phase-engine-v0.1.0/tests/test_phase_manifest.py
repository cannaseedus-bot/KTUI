"""kuhul-phases/v1 manifests: one JSON file per phase, chained by schema URI.

The tests hold the loader to what the format promises:

  regulation    schema id, phase vocabulary, uri/phase agreement, binding shape and captures
  honesty       a missing AIML file is reported, not assumed; an unknown chain scheme is an error
  chaining      `next` is followed by schema URI, cycles and repeated phases are bounded failures
  declarations  nothing is loaded into a kernel, executed or admitted - the report says what exists
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

import phase_manifest  # noqa: E402

SAMPLE = ROOT / "phases" / "json"


def manifest(root: Path, name: str, **overrides):
    record = {"schema": "kuhul-phases/v1", "phase": "Pop", "uri": "kuhul://phases/pop",
              "aiml": [], "bindings": [], "next": None, "authority": "declaration_only"}
    record.update(overrides)
    path = Path(root) / f"{name}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


class PhaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    # -- regulation ------------------------------------------------------------------------------
    def test_a_valid_manifest_loads(self):
        manifest(self.root, "pop")
        loaded = phase_manifest.load(self.root / "pop.json")
        self.assertTrue(loaded["ok"], loaded["problems"])
        self.assertEqual(loaded["manifest"]["phase"], "Pop")
        self.assertEqual(loaded["manifest"]["authority"], "declaration_only")

    def test_the_schema_id_is_required(self):
        manifest(self.root, "pop", schema="kuhul-phases/v9")
        loaded = phase_manifest.load(self.root / "pop.json")
        self.assertIn("schema", [problem["code"] for problem in loaded["problems"]])

    def test_an_unknown_phase_is_rejected(self):
        manifest(self.root, "zap", phase="Zap", uri="kuhul://phases/zap")
        loaded = phase_manifest.load(self.root / "zap.json")
        self.assertIn("phase", [problem["code"] for problem in loaded["problems"]])

    def test_the_uri_must_agree_with_the_phase(self):
        manifest(self.root, "pop", phase="Wo", uri="kuhul://phases/pop")
        loaded = phase_manifest.load(self.root / "pop.json")
        self.assertIn("uri_mismatch", [problem["code"] for problem in loaded["problems"]])

    def test_a_missing_aiml_file_is_reported(self):
        manifest(self.root, "pop", aiml=["../nope.aiml"])
        loaded = phase_manifest.load(self.root / "pop.json")
        self.assertIn("aiml_missing", [problem["code"] for problem in loaded["problems"]])
        tolerated = phase_manifest.load(self.root / "pop.json", check_files=False)
        self.assertTrue(tolerated["ok"])

    # -- bindings ---------------------------------------------------------------------------------
    def test_a_binding_needs_a_target(self):
        manifest(self.root, "pop", bindings=[{"pattern": "WHO IS *"}])
        loaded = phase_manifest.load(self.root / "pop.json")
        self.assertIn("binding_target", [problem["code"] for problem in loaded["problems"]])

    def test_a_capture_must_fit_the_pattern(self):
        manifest(self.root, "pop", bindings=[{"pattern": "HELLO", "srai": "WHAT IS {star:1}"}])
        loaded = phase_manifest.load(self.root / "pop.json")
        self.assertIn("binding_capture", [problem["code"] for problem in loaded["problems"]])
        manifest(self.root, "pop2", bindings=[{"pattern": "WHO IS *", "srai": "WHAT IS {star:1}"}])
        self.assertTrue(phase_manifest.load(self.root / "pop2.json")["ok"])

    def test_a_directive_binding_is_accepted(self):
        manifest(self.root, "sek", phase="Sek", uri="kuhul://phases/sek",
                 bindings=[{"pattern": "TELL ME ABOUT MY DOG", "directive": "COMPOSE pet",
                            "capability": "graph.relations.read"}])
        self.assertTrue(phase_manifest.load(self.root / "sek.json")["ok"])

    # -- chaining --------------------------------------------------------------------------------
    def test_the_shipped_chain_covers_all_six_phases(self):
        report = phase_manifest.chain("kuhul://phases/pop", root=SAMPLE)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["phases"], ["Pop", "Wo", "Yax", "Sek", "Ch'en", "Xul"])
        self.assertEqual(len(report["aiml"]), 6)
        self.assertEqual(len(report["chain"]), 6)
        self.assertEqual(report["authority"], "declaration_only")

    def test_a_chain_stops_at_next_null(self):
        manifest(self.root, "xul", phase="Xul", uri="kuhul://phases/xul", next=None)
        report = phase_manifest.chain("kuhul://phases/xul", root=self.root)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["phases"], ["Xul"])

    def test_a_cycle_is_a_bounded_failure(self):
        manifest(self.root, "pop", next="kuhul://phases/wo")
        manifest(self.root, "wo", phase="Wo", uri="kuhul://phases/wo", next="kuhul://phases/pop")
        report = phase_manifest.chain("kuhul://phases/pop", root=self.root)
        self.assertFalse(report["ok"])
        self.assertIn("chain_cycle", [problem["code"] for problem in report["problems"]])
        self.assertIn("pop.json", " ".join(report["chain"]))

    def test_a_repeated_phase_is_reported(self):
        manifest(self.root, "pop", next="kuhul://phases/pop2")
        # a second Pop manifest, no declared uri (so the uri/phase agreement does not fire first)
        manifest(self.root, "pop2", phase="Pop", next=None)
        report = phase_manifest.chain("kuhul://phases/pop", root=self.root)
        self.assertIn("phase_repeated", [problem["code"] for problem in report["problems"]])

    def test_an_unknown_chain_scheme_is_an_error(self):
        manifest(self.root, "pop", next="http://example.com/wo")
        report = phase_manifest.chain("kuhul://phases/pop", root=self.root)
        self.assertFalse(report["ok"])
        self.assertIn("chain_uri", [problem["code"] for problem in report["problems"]])

    def test_discovery_lists_the_phases_in_order(self):
        for name, phase in (("pop", "Pop"), ("wo", "Wo"), ("xul", "Xul")):
            manifest(self.root, name, phase=phase, uri=f"kuhul://phases/{name}")
        found = phase_manifest.discover(self.root)
        self.assertTrue(found["ok"], found["problems"])
        self.assertEqual(found["phases"], ["Pop", "Wo", "Xul"])

    def test_discovery_reports_a_duplicate_phase(self):
        manifest(self.root, "pop", phase="Pop")
        manifest(self.root, "pop2", phase="Pop")
        found = phase_manifest.discover(self.root)
        self.assertIn("duplicate_phase", [problem["code"] for problem in found["problems"]])

    # -- declaration only --------------------------------------------------------------------------
    def test_loading_executes_nothing(self):
        report = phase_manifest.chain("kuhul://phases/pop", root=SAMPLE)
        self.assertEqual(report["authority"], "declaration_only")
        self.assertNotIn("execution", report)
        source = (ROOT / "core" / "phase_manifest.py").read_text(encoding="utf-8")
        for forbidden in ("import aiml", "subprocess", "os.system", "Kernel("):
            self.assertNotIn(forbidden, source, f"{forbidden} must not appear in a loader")


if __name__ == "__main__":
    unittest.main()
