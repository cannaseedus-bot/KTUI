"""M21: the AIML corpus ports to one GML document - completely, and verifiably.

A port is only a port if nothing is lost and the claim can be re-checked. These tests convert the
corpus the host actually loads, then verify the document against the sources: one node per category,
one node per bank with its sha256, every `<srai>` either resolved to an edge or recorded as an
explicit `srai_missing` node.

The single-file projection is inspection data. It grants nothing, and the kernel still loads the .aiml
files.
"""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiml_to_gml  # noqa: E402
import phases  # noqa: E402


def parse(document: Path):
    gml2 = phases.core_module("gml2")
    return gml2.parse(Path(document).read_text(encoding="utf-8"))


def nodes_of(parsed, kind):
    found = []
    for entry in parsed.entries:
        if entry.name != "node":
            continue
        attributes = {attribute.name: attribute.value for attribute in entry.value.entries}
        if attributes.get("kind") == kind:
            found.append(attributes)
    return found


def node_attributes(parsed, kind):
    """Nodes of one kind with *all* their entries: some attributes repeat (constraint_name)."""
    found = []
    for entry in parsed.entries:
        if entry.name != "node":
            continue
        pairs = [(attribute.name, attribute.value) for attribute in entry.value.entries]
        if dict(pairs).get("kind") == kind:
            found.append(pairs)
    return found


class M21CorpusPort(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.document = Path(cls.folder.name) / "aiml-corpus.gml"
        cls.report = aiml_to_gml.write(cls.document)
        cls.parsed = parse(cls.document)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    # -- scope ----------------------------------------------------------------------------------
    def test_scope_is_the_host_corpus_not_the_vendored_one(self):
        banks = aiml_to_gml.host_banks()
        import knowledge
        self.assertEqual(len(banks), 18 + len(knowledge.paths()))
        self.assertTrue(all(bank.is_file() for bank in banks))
        self.assertGreater(len(aiml_to_gml.all_banks()), len(banks),
                           "the --all scope should be larger than the loaded corpus")

    # -- completeness ---------------------------------------------------------------------------
    def test_every_category_becomes_exactly_one_node(self):
        sources = aiml_to_gml.inventory(aiml_to_gml.host_banks())
        categories = nodes_of(self.parsed, "category")
        self.assertEqual(len(categories), sources["total_categories"])
        self.assertGreater(len(categories), 3000, "the loaded corpus now includes the knowledge banks")

    def test_every_bank_becomes_a_node_with_its_digest(self):
        sources = aiml_to_gml.inventory(aiml_to_gml.host_banks())
        banks = {node["path"]: node for node in nodes_of(self.parsed, "bank")}
        self.assertEqual(len(banks), sources["total_banks"])
        for bank in sources["banks"]:
            self.assertIn(bank["path"], banks, bank["path"])
            self.assertEqual(banks[bank["path"]]["digest"], bank["digest"], bank["path"])
            self.assertEqual(int(banks[bank["path"]]["categories"]), bank["categories"], bank["path"])

    def test_a_known_category_survives_the_port(self):
        categories = nodes_of(self.parsed, "category")
        memory = [node for node in categories if node.get("phrase") == "MY DOGS NAME IS *"]
        self.assertEqual(len(memory), 1)
        self.assertEqual(int(memory[0]["wildcard_count"]), 1)
        self.assertIn("MEMORY", memory[0]["template"])
        self.assertIn("memory", (memory[0]["template_kind"] + memory[0]["template"]).lower())

    def test_knowledge_questions_have_categories(self):
        categories = nodes_of(self.parsed, "category")
        saturn = [node for node in categories if node.get("phrase") == "WHAT IS SATURN"]
        self.assertEqual(len(saturn), 1, "the corpus projection must carry the knowledge banks")
        self.assertIn("planet", saturn[0]["template"].lower())

    def test_wildcard_counts_match_the_patterns(self):
        sources = aiml_to_gml.inventory(aiml_to_gml.host_banks())
        expected = sum(1 for category in sources["categories"] if category.wildcard_count)
        recorded = sum(1 for node in nodes_of(self.parsed, "category")
                       if int(node.get("wildcard_count") or 0))
        self.assertEqual(recorded, expected)

    # -- the redirect structure -----------------------------------------------------------------
    def test_redirects_are_edges_or_explicitly_missing(self):
        report = aiml_to_gml.check(self.document)
        self.assertTrue(report["ok"], report["problems"])
        self.assertGreater(report["resolved_redirects"], 0)
        self.assertEqual(report["errors"], [])
        sources = aiml_to_gml.inventory(aiml_to_gml.host_banks())
        total = sum(len(category.srai) for category in sources["categories"])
        self.assertEqual(report["resolved_redirects"] + report["unresolved_redirects"], total)

    def test_an_unresolvable_redirect_is_recorded_not_dropped(self):
        bank = Path(self.folder.name) / "orphan.aiml"
        bank.write_text(
            '<?xml version="1.0" encoding="UTF-8"?><aiml version="2.0">\n'
            '<category><pattern>PING</pattern><template><srai>NO SUCH TARGET</srai></template></category>\n'
            '</aiml>\n', encoding="utf-8")
        entry = aiml_to_gml.read_bank(bank)
        self.assertIsNone(entry["error"])
        self.assertEqual(entry["categories"][0].srai, ["NO SUCH TARGET"])
        single = aiml_to_gml.render(aiml_to_gml.inventory([bank]))
        parsed = phases.core_module("gml2").parse(single)
        missing = nodes_of(parsed, "srai_missing")
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["phrase"], "NO SUCH TARGET")

    # -- verification is a real check -----------------------------------------------------------
    def test_check_detects_a_tampered_digest(self):
        tampered = Path(self.folder.name) / "tampered.gml"
        text = self.document.read_text(encoding="utf-8")
        replacement = text.replace("sha256:", "sha256:0", 1)
        tampered.write_text(replacement, encoding="utf-8")
        report = aiml_to_gml.check(tampered)
        self.assertFalse(report["ok"])
        self.assertIn("digest_mismatch", [problem["code"] for problem in report["problems"]])

    def test_the_committed_document_is_in_sync_with_the_sources(self):
        committed = ROOT / "aiml-corpus.gml"
        self.assertTrue(committed.is_file(), "run: python aiml_to_gml.py --write")
        report = aiml_to_gml.check(committed)
        self.assertTrue(report["ok"], report["problems"])

    def test_registries_modules_and_documents_are_in_the_projection(self):
        registries = nodes_of(self.parsed, "registry")
        modules = nodes_of(self.parsed, "module")
        documents = nodes_of(self.parsed, "document")
        self.assertEqual(len(registries), len(aiml_to_gml.registry_docs()),
                         [item["name"] for item in registries])
        self.assertEqual(len(modules), len(aiml_to_gml.core_modules()),
                         "every core module must be projected")
        self.assertGreaterEqual(len(modules), 9, [item["name"] for item in modules])
        self.assertEqual(len(documents), 17)
        aiml_registry = next(pairs for pairs in node_attributes(self.parsed, "registry")
                             if dict(pairs).get("name") == "aiml-registry.gml")
        attributes = dict(aiml_registry)
        self.assertEqual(attributes["schema_id"], "aiml-gml/1")
        self.assertEqual(attributes["owner"], "gml.aiml")
        constraints = [value for name, value in aiml_registry if name == "constraint_name"]
        self.assertIn("pattern_wildcard_count", constraints)
        self.assertIn("endpoint_mode", constraints)
        edges = [entry for entry in self.parsed.entries if entry.name == "edge"]
        relations = [next((a.value for a in edge.value.entries if a.name == "relation"), "")
                     for edge in edges]
        self.assertGreater(relations.count("validated_by"), 0,
                           "a contract whose schema has a registry should point at it")

    def test_the_named_package_paths_are_covered(self):
        """The paths the review named: the AIML registry, phases, core, contracts, routing, integrations."""
        covered = set()
        for node in nodes_of(self.parsed, "bank") + nodes_of(self.parsed, "document") \
                + nodes_of(self.parsed, "module") + nodes_of(self.parsed, "registry"):
            covered.add(node.get("path") or node.get("name") or "")
        for expected in ("aiml-registry.gml", "pop.aiml", "chen.aiml", "gml2.py", "registry.py",
                         "category.gml", "xcfe.aiml", "kuhul-phases.aiml", "daemon-modes.aiml"):
            self.assertTrue(any(expected == item or item.endswith("/" + expected)
                                for item in covered), f"{expected} missing from the projection")

    def test_the_system_scope_adds_the_unloaded_declarations(self):
        folder = Path(self.folder.name)
        default_banks = aiml_to_gml.host_banks()
        with_system = folder / "system.gml"
        written = aiml_to_gml.write(with_system, system=True)
        self.assertGreater(len(written["documents"]), 17)
        self.assertGreater(len(written["registries"]), len(aiml_to_gml.registry_docs()))
        self.assertEqual(len(written["banks"]), len(default_banks),
                         "the system scope must not change which banks are included")

    def test_the_document_declares_that_it_grants_nothing(self):
        constraints = [entry for entry in self.parsed.entries
                       if entry.name in ("constraint", "operator")]
        names = []
        for entry in constraints:
            names += [attribute.value for attribute in entry.value.entries
                      if attribute.name == "name"]
        self.assertIn("no_grant_from_corpus", names)


if __name__ == "__main__":
    unittest.main()
