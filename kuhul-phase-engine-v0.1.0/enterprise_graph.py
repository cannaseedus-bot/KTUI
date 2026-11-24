"""Read-only demo graph inspector; NOT the host GML/2 validator."""
import argparse
import json
import re
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_graph(path=ROOT / 'graphs/enterprise.gml'):
    text = Path(path).read_text(encoding='utf-8')
    nodes = {}
    edges = []
    for kind, body in re.findall(r'\b(node|edge)\s*\[([^\[\]]*)\]', text):
        attrs = dict(re.findall(r'(\w+)\s+"([^"]*)"', body))
        if kind == 'node':
            if 'id' not in attrs or attrs['id'] in nodes:
                raise ValueError('missing or duplicate node ID')
            nodes[attrs['id']] = attrs
        else:
            edges.append(attrs)
    return nodes, edges


def validate():
    contract = json.loads((ROOT / 'contracts/enterprise-contract.json').read_text())
    text = (ROOT / 'graphs/enterprise.gml').read_text()
    assert f'schema "{contract["schema"]}"' in text
    assert 'authority "declaration_only"' in text
    assert contract['execution'] is False and contract['mutation'] is False
    nodes, edges = load_graph()
    for node in nodes.values():
        assert node.get('kind') in contract['allowed_node_kinds'], node
    for edge in edges:
        assert edge.get('relation') in contract['allowed_relations'], edge
        assert edge.get('source') in nodes and edge.get('target') in nodes, edge
    return nodes, edges


def impact_paths():
    nodes, edges = validate()
    by_source = {}
    for edge in edges:
        by_source.setdefault(edge['source'], []).append(edge)
    allowed = {'affects', 'contributes_to_cost', 'used_in', 'sold_in'}
    queue = deque([('risk_shipping', ['risk_shipping'])])
    paths = []
    while queue:
        current, path = queue.popleft()
        if nodes[current]['kind'] == 'market':
            paths.append(path)
            continue
        for edge in by_source.get(current, []):
            if edge['relation'] in allowed and edge['target'] not in path:
                queue.append((edge['target'], path + [edge['target']]))
    return paths


def scenario():
    observations = [json.loads(line) for line in (ROOT / 'data/market-observations.jsonl').read_text().splitlines() if line.strip()]
    def value(metric, subject=None):
        matches = [o['value'] for o in observations if o['metric'] == metric and (subject is None or o['subject'] == subject)]
        if len(matches) != 1:
            raise ValueError(f'expected exactly one observation: {metric}, {subject}')
        return matches[0]
    baseline = value('shipping_cost_usd_per_unit')
    pct = value('shipping_cost_change_pct')
    paths = impact_paths()
    affected = sorted({node for path in paths for node in path if node.startswith('product_')})
    deltas = {product: round(baseline * pct / 100 * value('shipping_cost_exposure_units', product), 2) for product in affected}
    return {'status': 'READ_ONLY_PROPOSAL', 'scenario': 'shock_15pct', 'paths': paths, 'product_unit_cost_increase_usd': deltas, 'execution': False, 'mutation': False, 'persistence': False, 'source': 'synthetic_fixture'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['validate', 'impact'])
    args = parser.parse_args()
    if args.command == 'validate':
        n, e = validate()
        print(json.dumps({'valid_demo_contract': True, 'nodes': len(n), 'edges': len(e)}))
    else:
        print(json.dumps(scenario(), indent=2))
