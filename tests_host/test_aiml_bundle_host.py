"""M13: the AIML bundle is consumed as declarations, never as authority.

The ledger numbered this M12 in review; M12 in this checkout is user memory, so the bundle guard is
M13. The four invariants under test:

  1 no independent AIML compiler - resolution goes through the package's Bundle and resolvers
  2 no authority from declarations - proposals carry authorized=False/persistence=None, always
  3 no direct database writes - proposing and admitting leave the memory log and task list untouched
  4 no bypass around the graph - a foreign scheme, foreign schema or unresolved node is a refusal
"""
import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiml_host  # noqa: E402
import functions  # noqa: E402
import phases  # noqa: E402

CATEGORY = "aiml://category/main#3"


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def contract_copy(folder: Path, *, requires: str | None = None) -> Path:
    """A copy of the six AIML contracts, optionally with a capability declared on the category."""
    shutil.copytree(phases.ROOT / "aiml_contracts", folder)
    if requires:
        category = folder / "category.gml"
        text = category.read_text(encoding="utf-8")
        text = text.replace(
            'node [ id 3 kind "category"',
            f'node [ id 3 kind "category" requires [ capability "{requires}" signature "string -> file" ]', 1)
        category.write_text(text, encoding="utf-8")
    return folder


class M13AimlBundleHost(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    # the bundle loads and validates through the package, not through this module
    def test_bundle_validates_with_the_package(self):
        report = aiml_host.validate()
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["state"], "BINDINGS_VALIDATED")
        self.assertEqual(len(report["contracts"]), 6)

    # a real SRAI relationship resolves, deterministically
    def test_proposal_is_deterministic_and_carries_no_authority(self):
        first = aiml_host.propose(CATEGORY)
        second = aiml_host.propose(CATEGORY)
        self.assertEqual(aiml_host.canonical(first), aiml_host.canonical(second))
        self.assertEqual(first["pattern"]["expression"], "WHO IS *")
        self.assertEqual([segment["kind"] for segment in first["template"]["segments"]],
                         ["text", "capture"])
        self.assertFalse(first["authorized"])
        self.assertIsNone(first["persistence"])
        verdict = aiml_host.admit(first)
        self.assertFalse(verdict["executes"])
        self.assertIsNone(verdict["persistence"])

    def test_srai_node_resolves_without_evaluating_it(self):
        proposal = aiml_host.propose("aiml://srai/main#4")
        self.assertEqual(proposal["kind"], "srai")
        self.assertEqual(proposal["pattern"]["expression"], "WHAT IS {star:1}")
        self.assertFalse(proposal["authorized"], "resolving an srai is not evaluating it")

    # refusals: foreign scheme/schema, unresolved nodes
    def test_foreign_scheme_is_refused(self):
        with self.assertRaises(aiml_host.BundleRefused):
            aiml_host.propose("gml://category/main#3")

    def test_foreign_schema_is_refused(self):
        folder = contract_copy(self.root / "foreign")
        (folder / "stray.gml").write_text(
            'graph [ schema "user-memory/1" graph_id "stray/main" contract "category" '
            'node [ id 1 kind "category" ] ]', encoding="utf-8")
        with self.assertRaises(aiml_host.BundleRefused):
            aiml_host.propose(CATEGORY, folder)

    def test_unresolved_reference_is_refused(self):
        for reference in ("aiml://pattern/main#99", "aiml://nothere/main#1"):
            with self.assertRaises(aiml_host.BundleRefused):
                aiml_host.propose(reference)

    # capabilities: declared, never authorized by declaration
    def test_unauthorized_capability_is_refused(self):
        folder = contract_copy(self.root / "capable", requires="shell.exec")
        proposal = aiml_host.propose(CATEGORY, folder)
        self.assertEqual(proposal["capabilities"], ["shell.exec"])
        refused = aiml_host.admit(proposal, allowlist=())
        self.assertFalse(refused["admitted"])
        self.assertEqual([reason["code"] for reason in refused["reasons"]], ["capability_not_allowed"])
        allowed = aiml_host.admit(proposal, allowlist=("shell.exec",))
        self.assertTrue(allowed["admitted"])
        self.assertFalse(allowed["executes"], "an allowlisted capability still does not execute here")
        self.assertIsNone(allowed["persistence"])

    # a proposal that claims authority is refused, not trusted
    def test_forged_authority_and_stale_bundle_are_refused(self):
        proposal = aiml_host.propose(CATEGORY)
        forged = aiml_host.admit(dict(proposal, authorized=True))
        self.assertFalse(forged["admitted"])
        self.assertIn("forged_authority", [reason["code"] for reason in forged["reasons"]])
        stale = aiml_host.admit(dict(proposal, bundle_state="REJECTED"))
        self.assertFalse(stale["admitted"])
        self.assertIn("stale_bundle", [reason["code"] for reason in stale["reasons"]])

    # nothing is written
    def test_proposing_and_admitting_write_nothing(self):
        watched = [ROOT / "logs" / "memory" / "user.events.jsonl", ROOT / "task-list.json"]
        before = [digest(path) for path in watched]
        aiml_host.validate()
        proposal = aiml_host.propose(CATEGORY)
        aiml_host.admit(proposal, allowlist=("shell.exec",))
        aiml_host.summary()
        functions.get("aiml_bundle_validate").handler(functions.ToolContext(ROOT))
        functions.get("aiml_propose").handler(functions.ToolContext(ROOT), CATEGORY)
        self.assertEqual([digest(path) for path in watched], before,
                         "the bundle adapter must not write to the memory log or task list")

    # and it is reachable through the typed registry, read-only
    def test_functions_are_registered_and_declarative(self):
        for name in ("aiml_bundle_validate", "aiml_propose"):
            entry = functions.get(name)
            self.assertIsNotNone(entry, f"{name} is not registered")
            self.assertIsNotNone(entry.handler)
        text = functions.get("aiml_propose").handler(functions.ToolContext(ROOT), CATEGORY)
        self.assertIn("authorized: False", text)
        self.assertIn("executes=False", text)


if __name__ == "__main__":
    unittest.main()
