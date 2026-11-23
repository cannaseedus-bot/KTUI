import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]

class PhaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / 'manifest.json').read_text())

    def test_phase_order(self):
        self.assertEqual(self.manifest['phase_order'], ['Pop', 'Wo', 'Yax', 'Sek', "Ch'en", 'Xul'])

    def test_all_aiml_parse(self):
        for path in sorted(ROOT.rglob('*.aiml')):
            with self.subTest(path=path.name):
                self.assertEqual(ET.parse(path).getroot().tag, 'aiml')

    def test_source_hashes(self):
        for rel, expected in self.manifest['source_sha256'].items():
            with self.subTest(file=rel):
                self.assertEqual(hashlib.sha256((ROOT / rel).read_bytes()).hexdigest(), expected)

    def test_phase_files_present(self):
        self.assertEqual(set(self.manifest['phase_files']), {'pop','wo','yax','sek','chen','xul'})
        for rel in self.manifest['phase_files'].values():
            self.assertTrue((ROOT / rel).is_file())

    def test_no_implicit_execution_claim(self):
        self.assertIn('no implicit execution', self.manifest['execution_policy'])

    def test_report_pattern_collisions(self):
        patterns = defaultdict(list)
        for path in sorted(ROOT.rglob('*.aiml')):
            for category in ET.parse(path).getroot().iter('category'):
                pattern = category.find('pattern')
                if pattern is not None:
                    key = ' '.join(''.join(pattern.itertext()).split()).upper()
                    patterns[key].append(str(path.relative_to(ROOT)))
        collisions = {k: v for k, v in patterns.items() if len(v) > 1}
        print('Pattern collisions (informational):', len(collisions))
        for key, sources in list(collisions.items())[:15]:
            print(' ', key, sources)
        self.assertTrue(patterns)

if __name__ == '__main__':
    unittest.main()
