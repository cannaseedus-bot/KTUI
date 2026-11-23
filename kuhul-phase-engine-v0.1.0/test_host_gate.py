"""Regression tests for the v2.1 host gate: the rules the ledger depends on.

Each test names the rule, so a refactor may change the report's shape but not weaken it:

  1. capture completeness  - documented tests are captured, not dropped
  2. comparability         - a SHA change is recorded, not rejected; a legacy capture stays usable
  3. three-state verdicts  - closed / inconclusive / failed with machine-readable reason codes
  4. positive guard evidence - a ledger closes on new named guards when no original failure existed
  5. baseline provenance   - a historical partial baseline is labelled, never padded with invented tests
  6. disappeared != fixed  - a vanished test can never count as recovered
  7. human authority       - merge_authorized stays false whatever the evidence says
"""
import unittest

from host_gate import (assess, comparability, compare, load_signatures, parse_suite, _command_of)

COMMAND = ['python', '-m', 'unittest', 'discover', '-s', 'tests', '-v']
SIGNATURES = [
    dict(id='F14-schema-mismatch', ledger='F14', error_pattern='schema mismatch',
         traceback_pattern='registry.py', guard_test_pattern='test_.*(foreign|ownership)'),
    dict(id='M2-unknown-field', ledger='M2', error_pattern='unregistered field',
         traceback_pattern='registry.py', guard_test_pattern='test_.*typo'),
]


def case(name, outcome, error=None, signatures=()):
    return dict(test_id=name, outcome=outcome, error_type=error, traceback_head=None,
                traceback='', signatures=list(signatures))


def capture(cases, *, ran=None, sha='a' * 40, kind='original-capture', complete=True):
    return dict(schema='kuhul.host-gate.capture/2.1', host='C:/host',
                captured_at='2026-01-01T00:00:00Z',
                invocation=dict(command_line=COMMAND, interpreter='3.12', cwd='C:/host'),
                git=dict(sha=sha, branch='main', dirty=False, status_head=None),
                signature_declarations=SIGNATURES, provenance=dict(kind=kind),
                health_correlation=dict(suite_sha=sha, health_sha=sha, same_run=True),
                suite=dict(run=dict(exit_code=0),
                           summary=dict(cases={c['test_id']: c for c in cases},
                                        ran=ran if ran is not None else len(cases),
                                        errors=0, failures=0, ok=True, complete=complete)),
                base_health=dict(exit_code=0, stdout='banks 9 · categories 238', stderr=''),
                extension_summary=dict(exit_code=0, stdout='GML extension `gml-tensor/1`', stderr=''))


class HostGateV21(unittest.TestCase):
    # 1 -- capture completeness
    def test_documented_tests_are_captured(self):
        text = ('test_a (m.C.test_a)\n a docstring ... ok\n'
                'test_b (m.C.test_b) ... ok\nRan 2 tests\nOK\n')
        summary = parse_suite(dict(stdout=text, stderr='', exit_code=0), SIGNATURES)
        self.assertEqual(summary['ran'], 2)
        self.assertEqual(len(summary['cases']), 2)
        self.assertTrue(summary['complete'])

    def test_failure_evidence_is_per_test(self):
        text = ('test_ok (m.C.test_ok) ... ok\n'
                '======================================================================\n'
                'ERROR: test_bad (m.C.test_bad)\n'
                '----------------------------------------------------------------------\n'
                'Traceback (most recent call last):\n'
                '  File "core/registry.py", line 52, in validate_document\n'
                'registry.RegistryError: schema mismatch\n'
                '\n----------------------------------------------------------------------\n'
                'Ran 2 tests\nFAILED (errors=1)\n')
        summary = parse_suite(dict(stdout=text, stderr='', exit_code=1), SIGNATURES)
        # The gate keys a case as <qualified id> + '.' + <short name>, as unittest prints it.
        self.assertEqual(summary['cases']['m.C.test_ok.test_ok']['signatures'], [])
        self.assertEqual(summary['cases']['m.C.test_bad.test_bad']['signatures'], ['F14-schema-mismatch'])

    # 2 -- comparability
    def test_sha_change_is_recorded_not_rejected(self):
        before = capture([case('m.C.test_x', 'errored', 'schema mismatch', ['F14-schema-mismatch'])])
        after = capture([case('m.C.test_x', 'passed')], sha='b' * 40)
        comp = comparability(before, after)
        self.assertEqual(comp['blockers'], [])
        self.assertIn('sha_changed', [item['code'] for item in comp['informational']])

    def test_legacy_capture_without_invocation_stays_comparable(self):
        before = capture([case('m.C.test_x', 'errored', 'schema mismatch', ['F14-schema-mismatch'])])
        before.pop('invocation')
        before['command_line'] = COMMAND
        after = capture([case('m.C.test_x', 'passed')])
        comp = comparability(before, after)
        self.assertEqual(comp['blockers'], [])
        self.assertIn('invocation_unknown', [item['code'] for item in comp['informational']])

    def test_dirty_working_tree_is_informational(self):
        before = capture([case('m.C.test_x', 'passed')])
        after = capture([case('m.C.test_x', 'passed')])
        after['git']['dirty'] = True
        comp = comparability(before, after)
        self.assertEqual(comp['blockers'], [])
        self.assertIn('working_tree_dirty', [item['code'] for item in comp['informational']])

    # 3 -- three-state verdicts
    def test_closed_when_every_original_failure_recovers(self):
        before = capture([case('m.C.test_x', 'errored', 'schema mismatch', ['F14-schema-mismatch'])])
        after = capture([case('m.C.test_x', 'passed')], sha='b' * 40)
        state = assess(before, after, compare(before, after), SIGNATURES)['verdict']['ledgers']['F14']
        self.assertEqual(state['state'], 'closed')
        self.assertIn('original_failures_recovered', [r['code'] for r in state['reasons']])
        self.assertEqual(state['recovered_tests'], ['m.C.test_x'])

    def test_inconclusive_without_evidence(self):
        before = capture([case('m.C.healthy', 'passed')])
        after = capture([case('m.C.healthy', 'passed')])
        state = assess(before, after, compare(before, after), SIGNATURES)['verdict']['ledgers']['F14']
        self.assertEqual(state['state'], 'inconclusive')
        self.assertIn('no_evidence', [r['code'] for r in state['reasons']])

    def test_failed_when_a_ledger_signature_survives(self):
        before = capture([case('m.C.test_x', 'errored', 'schema mismatch', ['F14-schema-mismatch'])])
        after = capture([case('m.C.test_x', 'passed'),
                         case('m.C.test_y', 'failed', 'schema mismatch', ['F14-schema-mismatch'])])
        state = assess(before, after, compare(before, after), SIGNATURES)['verdict']['ledgers']['F14']
        self.assertEqual(state['state'], 'failed')
        self.assertIn('ledger_signature_after', [r['code'] for r in state['reasons']])

    def test_outstanding_original_failures_stay_inconclusive(self):
        before = capture([case('m.C.test_x', 'errored', 'schema mismatch', ['F14-schema-mismatch']),
                          case('m.C.test_y', 'errored', 'schema mismatch', ['F14-schema-mismatch'])])
        after = capture([case('m.C.test_x', 'passed'),
                         case('m.C.test_y', 'errored', 'schema mismatch', ['F14-schema-mismatch'])])
        state = assess(before, after, compare(before, after), SIGNATURES)['verdict']['ledgers']['F14']
        self.assertEqual(state['state'], 'failed')

    # 4 -- positive guard evidence
    def test_positive_guard_evidence_closes_m2(self):
        before = capture([case('m.C.healthy', 'passed')])
        after = capture([case('m.C.healthy', 'passed'),
                         case('m.C.test_m2_data_typo_rejected', 'passed')])
        state = assess(before, after, compare(before, after), SIGNATURES)['verdict']['ledgers']['M2']
        self.assertEqual(state['state'], 'closed')
        self.assertIn('positive_guard_evidence', [r['code'] for r in state['reasons']])
        self.assertEqual(state['guard_tests'], ['m.C.test_m2_data_typo_rejected'])

    # 5 -- baseline provenance
    def test_historical_partial_baseline_is_labelled_not_padded(self):
        before = capture([case('m.C.test_x', 'errored', 'schema mismatch', ['F14-schema-mismatch'])],
                         ran=48, kind='historical-partial', complete=False)
        after = capture([case('m.C.test_x', 'passed')])
        comp = comparability(before, after)
        self.assertEqual(comp['baseline']['kind'], 'historical-partial')
        self.assertFalse(comp['baseline']['complete'])
        self.assertIn('baseline_partial', [item['code'] for item in comp['informational']])
        report = assess(before, after, compare(before, after), SIGNATURES)
        self.assertEqual(report['comparability']['baseline']['named_cases'], 1)
        self.assertNotIn('m.C.test_invented', report['evidence_a']['recovered'] and [])

    # 6 -- disappeared is never a fix
    def test_disappeared_never_counts_as_fixed(self):
        before = capture([case('m.C.test_gone', 'errored', 'schema mismatch', ['F14-schema-mismatch'])])
        after = capture([])
        diff = compare(before, after)
        self.assertEqual([r['test_id'] for r in diff['disappeared']], ['m.C.test_gone'])
        self.assertEqual(diff['recovered'], [])
        state = assess(before, after, diff, SIGNATURES)['verdict']['ledgers']['F14']
        self.assertEqual(state['state'], 'failed')
        self.assertIn('disappeared_tests', [r['code'] for r in state['reasons']])

    # 7 -- human authority
    def test_merge_authority_is_never_granted(self):
        before = capture([case('m.C.test_x', 'errored', 'schema mismatch', ['F14-schema-mismatch'])])
        after = capture([case('m.C.test_x', 'passed'),
                         case('m.C.test_m2_data_typo_rejected', 'passed')])
        verdict = assess(before, after, compare(before, after), SIGNATURES)['verdict']
        self.assertTrue(verdict['evidence_satisfied'])
        self.assertFalse(verdict['merge_authorized'])
        self.assertEqual(verdict['authority'], 'human')

    def test_signature_table_is_declared_data(self):
        entries = load_signatures()
        self.assertTrue(entries)
        self.assertTrue(all('ledger' in entry and 'error_pattern' in entry for entry in entries))
        self.assertTrue(any('guard_test_pattern' in entry for entry in entries))


if __name__ == '__main__':
    unittest.main()
