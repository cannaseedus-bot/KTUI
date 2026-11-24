"""Read-only EmbeddingGemma2 AIML vector adapter; no compiler, graph writes or execution."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np

FILES = {'pattern':'pattern_vectors.f32.npy','template':'template_vectors.f32.npy','category':'category_vectors.f32.npy'}
PAIRS = 'aiml_pattern_template_pairs.jsonl'

class VectorContractError(ValueError):
    pass

class AIMLVectorAdapter:
    def __init__(self, root):
        self.root = Path(root).expanduser()
        if not self.root.is_dir():
            raise FileNotFoundError(f'vector directory not found: {self.root}')
        self.manifest = json.loads((self.root/'manifest.json').read_text(encoding='utf-8'))
        self.arrays = {}
        for key, filename in FILES.items():
            arr = np.load(self.root/filename, mmap_mode='r', allow_pickle=False)
            if arr.ndim != 2 or arr.dtype != np.dtype('<f4') or arr.shape[0] == 0 or arr.shape[1] == 0:
                raise VectorContractError(f'{filename}: expected nonempty rank-2 float32 array')
            self.arrays[key] = arr
        shape = self.arrays['pattern'].shape
        if any(a.shape != shape for a in self.arrays.values()):
            raise VectorContractError('pattern/template/category vector shapes differ')
        self.rows, self.dimensions = shape
        self._pairs = None

    @staticmethod
    def _row_of(record, line_no):
        """The row a pair record belongs to.

        The producer writes `index` plus `A.vector_row`/`B.vector_row`; a synthetic fixture may write a
        flat `vector_row`. Both are accepted, and a record that contradicts itself is a contract error
        rather than a silent guess.
        """
        candidates = []
        if type(record.get('vector_row')) is int:
            candidates.append(('vector_row', record['vector_row']))
        if type(record.get('index')) is int:
            candidates.append(('index', record['index']))
        for lane in ('A', 'B'):
            lane_record = record.get(lane)
            if isinstance(lane_record, dict) and type(lane_record.get('vector_row')) is int:
                candidates.append((f'{lane}.vector_row', lane_record['vector_row']))
        if not candidates:
            raise VectorContractError(f'JSONL line {line_no}: no integer row reference')
        values = {value for _, value in candidates}
        if len(values) > 1:
            raise VectorContractError(
                f'JSONL line {line_no}: contradictory row references {sorted(values)}')
        return values.pop()

    def pairs(self):
        if self._pairs is None:
            rows = {}
            with (self.root/PAIRS).open(encoding='utf-8') as stream:
                for line_no, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise VectorContractError(f'JSONL line {line_no}: {exc}') from exc
                    if not isinstance(obj, dict):
                        raise VectorContractError(f'JSONL line {line_no}: not an object')
                    row = self._row_of(obj, line_no)
                    if row < 0 or row >= self.rows or row in rows:
                        raise VectorContractError(
                            f'JSONL line {line_no}: out-of-range or duplicate row {row}')
                    rows[row] = obj
            if len(rows) != self.rows:
                raise VectorContractError(f'JSONL coverage {len(rows)} != vectors {self.rows}')
            self._pairs = rows
            self._by_pattern = {}
            for row, obj in rows.items():
                pattern = str(obj.get('pattern') or '')
                if pattern:
                    self._by_pattern.setdefault(pattern.upper(), []).append(row)
        return self._pairs

    # -- retrieval without an encoder -----------------------------------------------------------
    def retrieve_by_row(self, row, lane='pattern', top_k=5, minimum_score=None):
        """Nearest neighbours of an existing row: no encoder is needed, no text is embedded."""
        if type(row) is not int or not 0 <= row < self.rows:
            raise VectorContractError(f'row must be 0..{self.rows - 1}')
        vector = np.asarray(self.arrays[lane][row], dtype=np.float32)
        result = self.retrieve(vector, lane=lane, top_k=top_k, minimum_score=minimum_score)
        result['query'] = {'kind': 'existing_row', 'row': row, 'lane': lane}
        return result

    def lookup(self, text, field='pattern'):
        """Exact lookup of a pattern (the corpus has no encoder here, so no fuzzy text embed)."""
        self.pairs()
        if field != 'pattern':
            raise VectorContractError('only the pattern lane can be looked up by text')
        rows = self._by_pattern.get(str(text or '').strip().upper(), [])
        return {'status': 'EXACT_MATCH' if rows else 'NO_ENCODER_MATCH', 'rows': rows[:20],
                'authority': 'data_only', 'execution': False}

    def for_text(self, text, top_k=5, lane='pattern'):
        """Candidates for a text query: exact pattern hit, then its vector neighbours.

        There is no text encoder in this repository, so a phrase that is not a known pattern comes
        back as NO_ENCODER_MATCH rather than a fabricated embedding.
        """
        found = self.lookup(text)
        if not found['rows']:
            return dict(found, candidates=[], note='no encoder available for unseen text')
        result = self.retrieve_by_row(found['rows'][0], lane=lane, top_k=top_k)
        result['query'] = {'kind': 'exact_pattern', 'text': str(text).strip().upper(),
                           'row': found['rows'][0]}
        return result

    def validate(self, check_pairs=True):
        if check_pairs:
            self.pairs()
        return {'status':'VALIDATED_READ_ONLY','rows':self.rows,'dimensions':self.dimensions,
                'manifest_present':True,'pairs_checked':check_pairs,'execution':False,
                'mutation':False,'persistence':False}

    def retrieve(self, vector, lane='pattern', top_k=5, chunk_size=8192, minimum_score=None):
        if lane not in FILES:
            raise VectorContractError('unknown vector lane')
        if not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise VectorContractError('top_k must be 1..100')
        query = np.asarray(vector, dtype=np.float32)
        if query.shape != (self.dimensions,) or not np.isfinite(query).all():
            raise VectorContractError(f'query must be finite float32 vector [{self.dimensions}]')
        qnorm = float(np.linalg.norm(query))
        if qnorm <= 0:
            raise VectorContractError('query vector must be nonzero')
        query = query/qnorm
        array = self.arrays[lane]
        winners = []
        for start in range(0, self.rows, chunk_size):
            block = np.asarray(array[start:start+chunk_size], dtype=np.float32)
            norms = np.linalg.norm(block, axis=1)
            scores = (block @ query) / np.where(norms > 0, norms, np.inf)
            for offset, score in enumerate(scores):
                if np.isfinite(score) and (minimum_score is None or float(score) >= minimum_score):
                    winners.append((float(score), start+offset))
            # bound memory: preserve all ties deterministically by row ID
            if len(winners) > top_k*2:
                winners = sorted(winners, key=lambda p:(-p[0],p[1]))[:top_k]
        winners = sorted(winners, key=lambda p:(-p[0],p[1]))[:top_k]
        pair_map = self.pairs()
        return {'status':'READ_ONLY_CANDIDATES','lane':lane,'candidates':[
            {'vector_row':row,'cosine_score':round(score,8),'binding':pair_map[row],
             'admission':'PENDING_XCFE'} for score,row in winners],
            'execution':False,'mutation':False,'persistence':False}

    def propose_graph_bindings(self, retrieval):
        """Projection only: refs are candidates, not admitted graph edges."""
        if retrieval.get('status') != 'READ_ONLY_CANDIDATES':
            raise VectorContractError('requires retrieval candidates')
        return {'schema':'aiml-gml-vector-proposal/1','authority':'declaration_only',
                'edges':[{'source':f'aiml://vector/{c["vector_row"]}/pattern',
                          'target':f'aiml://vector/{c["vector_row"]}/template',
                          'relation':'pattern_template_candidate',
                          'vector_row':c['vector_row'],'score':c['cosine_score'],
                          'status':'PENDING_XCFE'} for c in retrieval['candidates']],
                'execution':False,'mutation':False,'persistence':False}


    # -- ranking is not authorization ------------------------------------------------------------
    @staticmethod
    def _tokens(text):
        return [token for token in ''.join(
            character if (character.isalnum() or character in '*_ ') else ' '
            for character in str(text or '').upper()).split() if token]

    def compatible(self, pattern, text):
        """AIML wildcard compatibility: could this pattern match the text at all?

        A similarity score says "these are semantically close"; it says nothing about whether the
        pattern can bind the input. That is a separate structural check, and it stays separate.
        """
        pattern_tokens = self._tokens(pattern)
        text_tokens = self._tokens(text)

        def walk(pi, ti):
            if pi == len(pattern_tokens):
                return ti == len(text_tokens)
            token = pattern_tokens[pi]
            if token in ('*', '_'):
                for size in range(len(text_tokens) - ti, 0, -1):
                    if walk(pi + 1, ti + size):
                        return True
                return False
            if ti < len(text_tokens) and text_tokens[ti] == token:
                return walk(pi + 1, ti + 1)
            return False

        return walk(0, 0)

    def rank_and_filter(self, text, top_k=5, lane='pattern'):
        """Candidates that pass the structural filter; the rest are reported, not silently kept."""
        retrieval = self.for_text(text, top_k=top_k, lane=lane)
        kept, dropped = [], []
        for candidate in retrieval.get('candidates') or []:
            binding = candidate.get('binding') or {}
            pattern = str(binding.get('pattern') or '')
            entry = {'vector_row': candidate['vector_row'],
                     'cosine_score': candidate['cosine_score'],
                     'pattern': pattern,
                     'source_path': binding.get('source_path'),
                     'admission': 'PENDING_XCFE'}
            if pattern and not self.compatible(pattern, text):
                entry['dropped_because'] = 'pattern cannot bind this input'
                dropped.append(entry)
            else:
                kept.append(entry)
        return {'schema': 'aiml-vector-candidates/1', 'status': 'RANKED_AND_FILTERED',
                'query': retrieval.get('query'), 'lane': lane,
                'compatible': kept, 'dropped_incompatible': dropped,
                'note': 'the score ranks; compatibility filters; admission belongs to XCFE',
                'execution': False, 'mutation': False, 'persistence': False}


def main():
    parser = argparse.ArgumentParser(description='Read-only AIML EmbeddingGemma2 vector bridge')
    parser.add_argument('--vectors', required=True, help='directory with manifest, three .npy arrays and pairs JSONL')
    parser.add_argument('command', choices=['validate','retrieve'])
    parser.add_argument('--query-vector', help='JSON file containing a list of embedding floats (no encoder included)')
    parser.add_argument('--lane', choices=list(FILES), default='pattern')
    parser.add_argument('--top-k', type=int, default=5)
    args = parser.parse_args()
    adapter = AIMLVectorAdapter(args.vectors)
    if args.command == 'validate':
        result = adapter.validate()
    else:
        if not args.query_vector:
            parser.error('retrieve requires --query-vector')
        query = json.loads(Path(args.query_vector).read_text(encoding='utf-8'))
        result = adapter.retrieve(query, lane=args.lane, top_k=args.top_k)
        result['graph_proposal'] = adapter.propose_graph_bindings(result)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
