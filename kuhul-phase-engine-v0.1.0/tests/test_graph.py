import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enterprise_graph import validate, impact_paths, scenario

class EnterpriseGraphTests(unittest.TestCase):
    def test_schema_and_endpoints(self):
        nodes, edges = validate()
        self.assertEqual(len(nodes), 18)
        self.assertEqual(len(edges), 21)

    def test_impact_reaches_both_markets(self):
        paths = impact_paths()
        self.assertEqual({p[-1] for p in paths}, {'market_us', 'market_eu'})

    def test_scenario_is_read_only(self):
        result = scenario()
        self.assertEqual(result['product_unit_cost_increase_usd'], {'product_a': 3.0, 'product_b': 1.5})
        self.assertFalse(result['execution'])
        self.assertFalse(result['mutation'])
        self.assertFalse(result['persistence'])

if __name__ == '__main__':
    unittest.main()
