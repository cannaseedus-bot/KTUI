import json
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapters.embeddinggemma2 import AIMLVectorAdapter, VectorContractError

class VectorAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'manifest.json').write_text(json.dumps({'producer':'EmbeddingGemma2'}))
        self.arr = np.array([[1,0],[0,1],[-1,0]],dtype=np.float32)
        for name in ('pattern','template','category'):
            np.save(self.root/f'{name}_vectors.f32.npy', self.arr)
        (self.root/'aiml_pattern_template_pairs.jsonl').write_text(''.join(json.dumps({'vector_row':i,'pattern':f'P{i}','template':f'T{i}'})+'\n' for i in range(3)))

    def test_validate(self):
        self.assertEqual(AIMLVectorAdapter(self.root).validate()['rows'],3)

    def test_retrieve_and_graph_proposal_are_read_only(self):
        a = AIMLVectorAdapter(self.root)
        r = a.retrieve([1,0],top_k=2)
        self.assertEqual([c['vector_row'] for c in r['candidates']],[0,1])
        p = a.propose_graph_bindings(r)
        self.assertFalse(p['execution']); self.assertFalse(p['mutation']); self.assertFalse(p['persistence'])
        self.assertEqual(p['edges'][0]['status'],'PENDING_XCFE')

    def test_bad_shape_rejected(self):
        np.save(self.root/'category_vectors.f32.npy',self.arr[:2])
        with self.assertRaises(VectorContractError): AIMLVectorAdapter(self.root)

    def test_duplicate_row_rejected(self):
        with (self.root/'aiml_pattern_template_pairs.jsonl').open('a') as f: f.write('{"vector_row":0}\n')
        with self.assertRaises(VectorContractError): AIMLVectorAdapter(self.root).validate()

    def test_invalid_query_rejected(self):
        with self.assertRaises(VectorContractError): AIMLVectorAdapter(self.root).retrieve([1,2,3])

    def test_zero_vector_rejected(self):
        with self.assertRaises(VectorContractError): AIMLVectorAdapter(self.root).retrieve([0,0])

    def test_no_implicit_execution(self):
        a=AIMLVectorAdapter(self.root)
        self.assertEqual(a.retrieve([1,0])['candidates'][0]['admission'],'PENDING_XCFE')

    # -- the producer's pair schema ------------------------------------------------------------
    def real_shape(self):
        """Rewrite the fixtures in the shape the producer actually writes."""
        records = [
            {'schema': 'micronaut.aiml.pi-radius-pair.v1', 'index': 0,
             'A': {'kind': 'aiml_pattern_context', 'vector_row': 0},
             'B': {'kind': 'aiml_template', 'vector_row': 0},
             'pattern': 'WHO IS *', 'template': '<template>a</template>'},
            {'index': 1, 'A': {'vector_row': 1}, 'B': {'vector_row': 1},
             'pattern': 'WHAT IS AI', 'template': '<template>b</template>'},
            {'index': 2, 'A': {'vector_row': 2}, 'B': {'vector_row': 2},
             'pattern': 'HELLO', 'template': '<template>c</template>'},
        ]
        (self.root / 'aiml_pattern_template_pairs.jsonl').write_text(
            ''.join(json.dumps(record) + '\n' for record in records), encoding='utf-8')

    def test_the_producer_pair_schema_is_accepted(self):
        self.real_shape()
        adapter = AIMLVectorAdapter(self.root)
        self.assertEqual(adapter.validate()['rows'], 3)
        # lookups are exact: "WHO IS *" is a pattern, "who is saturn" is an input. Without an encoder
        # an input can only reach the candidates through the wildcard filter, never by lookup.
        self.assertEqual(adapter.lookup('who is *')['rows'], [0])
        self.assertEqual(adapter.lookup('who is saturn')['rows'], [])

    def test_contradictory_row_references_are_rejected(self):
        (self.root / 'aiml_pattern_template_pairs.jsonl').write_text(
            json.dumps({'index': 0, 'A': {'vector_row': 1}}) + '\n' + ''.join(
                json.dumps({'index': i}) + '\n' for i in (1, 2)), encoding='utf-8')
        with self.assertRaisesRegex(VectorContractError, 'contradictory'):
            AIMLVectorAdapter(self.root).validate()

    # -- retrieval without an encoder -----------------------------------------------------------
    def test_row_retrieval_needs_no_encoder(self):
        self.real_shape()
        adapter = AIMLVectorAdapter(self.root)
        result = adapter.retrieve_by_row(0, top_k=2)
        self.assertEqual([c['vector_row'] for c in result['candidates']][0], 0)
        self.assertEqual(result['query'], {'kind': 'existing_row', 'row': 0, 'lane': 'pattern'})

    def test_unseen_text_is_reported_not_embedded(self):
        self.real_shape()
        result = AIMLVectorAdapter(self.root).for_text('something unseen')
        self.assertEqual(result['status'], 'NO_ENCODER_MATCH')
        self.assertEqual(result['candidates'], [])
        self.assertIn('no encoder', result['note'])

    # -- ranking is not authorization ------------------------------------------------------------
    def test_compatibility_is_a_separate_structural_check(self):
        adapter = AIMLVectorAdapter(self.root)
        self.assertTrue(adapter.compatible('WHO IS *', 'who is saturn'))
        self.assertFalse(adapter.compatible('WHAT IS AI', 'who is saturn'))
        self.assertTrue(adapter.compatible('HELLO', 'hello'))

    def test_incompatible_candidates_are_dropped_and_reported(self):
        self.real_shape()
        adapter = AIMLVectorAdapter(self.root)
        result = adapter.rank_and_filter('hello', top_k=3)
        patterns = [row['pattern'] for row in result['compatible']]
        dropped = [row['pattern'] for row in result['dropped_incompatible']]
        self.assertIn('HELLO', patterns)
        self.assertTrue(dropped, 'semantic neighbours should be filtered by structure')
        self.assertTrue(all(row['dropped_because'] for row in result['dropped_incompatible']))
        self.assertEqual({row['admission'] for row in result['compatible']}, {'PENDING_XCFE'})
        self.assertIn('admission belongs to XCFE', result['note'])

    def test_scoring_survives_the_filter(self):
        self.real_shape()
        adapter = AIMLVectorAdapter(self.root)
        result = adapter.rank_and_filter('hello', top_k=3)
        for row in result['compatible'] + result['dropped_incompatible']:
            self.assertIsInstance(row['cosine_score'], float)
            self.assertGreaterEqual(row['cosine_score'], -1.0)
            self.assertLessEqual(row['cosine_score'], 1.0)


if __name__ == '__main__': unittest.main()
