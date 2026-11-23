"""Two declaration-level guards that sit beside test_merge_guards.py.

`test_merge_guards.py` covers the document side of M2 (a misspelled `data.vaule`, `graph.directde`,
or an invalid policy enum is rejected). These cover the registry side of the same claim, plus the
shape that tightening must not break:

  - deleting a graph-level or `data.value` declaration fails closed at bootstrap, so a declaration
    cannot quietly disappear and leave the check unenforced;
  - repeated `value` entries inside `data` stay legal, because that is how valid tensor data is
    written and a stricter M2 must not reject it.
"""
import sys, unittest, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))
from gml2 import parse, Block
from registry import load_registry, validate_document, RegistryError


def values(block, name):
    return [entry for entry in block.entries if entry.name == name]


def blocks(block, name):
    """A block attribute's payload is the nested Block; the attribute itself only names it."""
    return [entry.value for entry in block.entries
            if entry.name == name and isinstance(entry.value, Block)]


class DeclarationGuards(unittest.TestCase):
    def test_graph_declaration_removed_fails_closed(self):
        """Deleting `field [ path "graph" name "coverage_policy" … ]` must fail at bootstrap."""
        text = (ROOT / 'schemas/tensor-registry.gml').read_text()
        text = '\n'.join(line for line in text.splitlines()
                         if 'name "coverage_policy"' not in line)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'registry.gml'
            path.write_text(text)
            with self.assertRaisesRegex(RegistryError, 'missing field declarations'):
                load_registry(path)

    def test_data_value_declaration_removed_fails_closed(self):
        """Same for `field [ path "data" name "value" … ]`."""
        text = (ROOT / 'schemas/tensor-registry.gml').read_text()
        text = '\n'.join(line for line in text.splitlines()
                         if 'path "data" name "value"' not in line)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'registry.gml'
            path.write_text(text)
            with self.assertRaisesRegex(RegistryError, 'missing field declarations'):
                load_registry(path)

    def test_repeated_data_values_stay_legal(self):
        """The normal shape of tensor data: several `value` entries in one `data` block."""
        doc = parse((ROOT / 'contracts/col_a.gml').read_text())
        data = blocks(doc, 'data')[0]
        self.assertEqual(len(values(data, 'value')), 4)
        self.assertTrue(validate_document(doc, load_registry()))


if __name__ == '__main__':
    unittest.main()
