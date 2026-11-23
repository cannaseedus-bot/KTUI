#!/usr/bin/env python3
"""Read-only host evidence collector, v2.1. It reports evidence; it never authorizes merging.

What v2.1 changes relative to v2:

  capture hygiene       every capture records the exact invocation, the interpreter, the git SHA and
                        working-tree state, its timestamps and duration, and whether the health
                        commands ran in the same invocation as the suite. A SHA change between
                        captures is recorded as informational, not rejected: applying a patch moves
                        the commit on purpose.
  three-state verdicts  each ledger reports `closed`, `inconclusive` or `failed`, each with
                        machine-readable reason codes and the test IDs that support the call.
  positive guards       a ledger can close on newly introduced, named regression tests passing even
                        when no original failure was separately observable (M2's case).
  evidence != authority `evidence_satisfied` is reachable independently of `merge_authorized`, which
                        stays false unconditionally. The ledger and a human decide closure.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SIGNATURE_FILE = Path(__file__).with_name('signatures.json')
LEDGERS = ('F14', 'M2')
BAD = {'failed', 'errored'}
CAPTURE_SCHEMA = 'kuhul.host-gate.capture/2.1'
REPORT_SCHEMA = 'kuhul.host-gate.report/2.1'

# unittest prints a documented test as name, docstring, then the status on three lines. Joining them
# keeps per-test capture complete; without it those tests vanish and completeness can never be true.
SPLIT_VERBOSE = re.compile(
    r'^(?P<id>.+? \([^()]+\))\s*\n(?P<doc>.*?) \.\.\. '
    r'(?P<status>ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)\s*$', re.M)
VERBOSE = re.compile(
    r'^.+? \([^()]+\) \.\.\. (?:ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)\s*$', re.M)


def normalise(text):
    """Join the docstring-split verbose form back into one line."""
    return SPLIT_VERBOSE.sub(lambda m: f"{m.group('id')} ... {m.group('status')}", text)


def run(cmd, cwd, timeout):
    # Captured output must be lossless: the child prints with the host locale unless told
    # otherwise, and decoding cp1252 bytes as utf-8 replaces '·' with U+FFFD in the evidence.
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                              env=env, timeout=timeout, errors='replace')
        return dict(command_line=cmd, exit_code=proc.returncode, stdout=proc.stdout,
                    stderr=proc.stderr, timed_out=False,
                    duration_seconds=round(time.monotonic() - started, 3))
    except subprocess.TimeoutExpired as exc:
        def decode(value):
            return value.decode('utf-8', 'replace') if isinstance(value, bytes) else (value or '')
        return dict(command_line=cmd, exit_code=None, stdout=decode(exc.stdout),
                    stderr=decode(exc.stderr), timed_out=True,
                    duration_seconds=round(time.monotonic() - started, 3))


def git_info(host):
    """SHA, branch and working-tree state. Dirtiness is recorded, never used as a pass/fail gate."""
    def capture(args):
        result = run(['git', *args], host, 15)
        return result['stdout'].strip() if result['exit_code'] == 0 else None
    # The gate's own artifacts are outputs of this tool: comparing a fresh capture against the
    # previous committed one always looks like an edit, so they are excluded from the dirtiness
    # measure. Everything else tracked still counts.
    GATE_OUTPUTS = ('host-gate-',)
    def _is_output(line):
        return any(name in line for name in GATE_OUTPUTS)
    tracked_raw = capture(['status', '--porcelain', '-uno']) or ''
    tracked_lines = [line for line in tracked_raw.splitlines() if not _is_output(line)]
    tracked = '\n'.join(tracked_lines)
    everything = capture(['status', '--porcelain']) or ''
    untracked = [line[3:] for line in everything.splitlines()
                 if line.startswith('??') and not _is_output(line)]
    return dict(sha=capture(['rev-parse', 'HEAD']),
                branch=capture(['rev-parse', '--abbrev-ref', 'HEAD']),
                # `dirty` is about tracked content: that is what the suites measure. Untracked scratch
                # files are recorded separately instead of being conflated with an edited tree.
                dirty=None if tracked is None else bool(tracked),
                status_head=None if not tracked_lines else '\n'.join(tracked_lines[:20]),
                untracked_head=untracked[:20])


def load_signatures(path=SIGNATURE_FILE):
    entries = json.loads(Path(path).read_text(encoding='utf-8'))['signatures']
    ids = set()
    for item in entries:
        if item['id'] in ids or item['ledger'] not in LEDGERS:
            raise ValueError('duplicate or unknown signature declaration')
        ids.add(item['id'])
        for key in ('error_pattern', 'traceback_pattern'):
            re.compile(item[key], re.I)
        if 'guard_test_pattern' in item:
            re.compile(item['guard_test_pattern'], re.I)
    return entries


def classify(error_type, traceback, signatures):
    return [s['id'] for s in signatures
            if re.search(s['error_pattern'], error_type or '', re.I)
            and re.search(s['traceback_pattern'], traceback or '', re.I)]


def parse_suite(result, signatures):
    output = normalise(result['stdout'] + '\n' + result['stderr'])
    outcomes = {'ok': 'passed', 'FAIL': 'failed', 'ERROR': 'errored', 'expected failure': 'xfailed',
                'unexpected success': 'failed'}
    cases = {}
    for line in output.splitlines():
        match = re.match(r'^(.+?) \(([^()]+)\) \.\.\. '
                         r'(ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)\s*$',
                         line.strip())
        if match:
            raw = match.group(3)
            outcome = 'skipped' if raw.startswith('skipped') else outcomes[raw]
            test_id = match.group(2) + '.' + match.group(1)
            cases[test_id] = dict(test_id=test_id, outcome=outcome, error_type=None,
                                  traceback_head=None, traceback='', signatures=[])
    header = re.compile(r'^={5,}\n(?:FAIL|ERROR): (.+?) \(([^()]+)\)\n-{5,}\n', re.M)
    matches = list(header.finditer(output))
    for index, match in enumerate(matches):
        block = output[match.end(): matches[index + 1].start() if index + 1 < len(matches) else len(output)]
        block = re.split(r'\n-{5,}\nRan \d+ tests?', block, maxsplit=1)[0]
        test_id = match.group(2) + '.' + match.group(1)
        outcome = 'errored' if 'ERROR:' in output[match.start():match.end()] else 'failed'
        lines = block.strip().splitlines()
        exception = next((line.strip() for line in reversed(lines)
                          if re.match(r'^[\w.]+(?:Error|Exception|Failure):', line.strip())), '')
        frame = next((line.strip() for line in lines if line.strip().startswith('File ')), '')
        error_type = exception.split(':', 1)[1].strip() if ':' in exception else exception
        cases[test_id] = dict(test_id=test_id, outcome=outcome, error_type=error_type,
                              traceback_head=frame, traceback=block,
                              signatures=classify(error_type, block, signatures))
    count = re.search(r'Ran (\d+) tests?', output)
    errors = re.search(r'errors=(\d+)', output)
    failures = re.search(r'failures=(\d+)', output)
    ran = int(count.group(1)) if count else None
    return dict(cases=cases, ran=ran, errors=int(errors.group(1)) if errors else 0,
                failures=int(failures.group(1)) if failures else 0,
                ok=result['exit_code'] == 0 and bool(re.search(r'^OK\s*$', output, re.M)),
                complete=bool(ran) and len(cases) == ran)


def snapshot(host, timeout, command, signatures, provenance_kind='original-capture'):
    suite = run(command, host, timeout)
    base_health = run([sys.executable, '-c', 'import phases; print(phases.base_health())'],
                      host.parent, timeout)
    extension = run([sys.executable, '-c', 'import phases; print(phases.extension_summary())'],
                    host.parent, timeout)
    git = git_info(host)
    return dict(schema=CAPTURE_SCHEMA,
                captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                host=str(host),
                invocation=dict(command_line=list(command), interpreter=sys.version.split()[0],
                                cwd=str(host)),
                git=git,
                signature_declarations=signatures,
                provenance=dict(kind=provenance_kind),
                health_correlation=dict(suite_sha=git.get('sha'), health_sha=git.get('sha'),
                                        same_run=True,
                                        note='health commands ran in this same invocation, after the suite'),
                suite=dict(run=suite, summary=parse_suite(suite, signatures)),
                base_health=base_health, extension_summary=extension)


def compare(before, after):
    old = before['suite']['summary']['cases']
    new = after['suite']['summary']['cases']
    recovered, disappeared, new_failures, unchanged, changed = [], [], [], [], []
    for name in sorted(set(old) | set(new)):
        was, now = old.get(name), new.get(name)
        record = dict(test_id=name,
                      before=was['outcome'] if was else 'absent',
                      after=now['outcome'] if now else 'absent',
                      before_signatures=was.get('signatures', []) if was else [],
                      after_signatures=now.get('signatures', []) if now else [])
        if was and was['outcome'] in BAD and now and now['outcome'] == 'passed':
            recovered.append(record)
        elif was and not now:
            disappeared.append(record)
        elif now and now['outcome'] in BAD and (not was or was['outcome'] not in BAD):
            new_failures.append(record)
        elif was and now and was['outcome'] == now['outcome']:
            unchanged.append(record)
        else:
            changed.append(record)
    matched = {signature['id']: [] for signature in before['signature_declarations']}
    unmatched = []
    for record in recovered:
        if record['before_signatures']:
            for signature in record['before_signatures']:
                matched.setdefault(signature, []).append(record['test_id'])
        else:
            unmatched.append(record['test_id'])
    return dict(recovered=recovered, recovered_matched=matched, recovered_unmatched=unmatched,
                disappeared=disappeared, new_failures=new_failures, unchanged=unchanged,
                changed=changed)


def _ledger_of(signature_id):
    return signature_id.split('-', 1)[0]


def _command_of(capture):
    """A v2.1 capture nests the invocation; an older or reconstructed one keeps command_line flat."""
    return (capture.get('invocation') or {}).get('command_line') or capture.get('command_line')


def comparability(before, after):
    """What changed between the two captures. A SHA move is recorded, not treated as a failure."""
    result = dict(informational=[], blockers=[])
    if before['host'] != after['host']:
        result['blockers'].append(dict(code='different_host',
                                       detail=f"{before['host']} != {after['host']}"))
    command_before, command_after = _command_of(before), _command_of(after)
    if not (before.get('invocation') or {}).get('command_line') \
            or not (after.get('invocation') or {}).get('command_line'):
        result['informational'].append(dict(code='invocation_unknown',
                                            detail='one capture predates invocation recording; '
                                                   'comparison fell back to its flat command_line'))
    if command_before is not None and command_after is not None and command_before != command_after:
        result['blockers'].append(dict(code='different_suite_command',
                                       detail='the two captures ran different suite commands'))
    if before.get('signature_declarations') != after.get('signature_declarations'):
        result['blockers'].append(dict(code='different_signatures',
                                       detail='signature declarations changed between captures'))
    sha_before = (before.get('git') or {}).get('sha')
    sha_after = (after.get('git') or {}).get('sha')
    if sha_before != sha_after:
        result['informational'].append(dict(code='sha_changed',
                                            detail=f'{sha_before or "unknown"} -> {sha_after or "unknown"}'))
    if (after.get('git') or {}).get('dirty'):
        result['informational'].append(dict(code='working_tree_dirty',
                                            detail='captured with tracked changes; recorded, not rejected'))
    untracked = (after.get('git') or {}).get('untracked_head') or []
    if untracked:
        result['informational'].append(dict(code='untracked_files',
                                            detail=f'{len(untracked)} untracked entr(y/ies); '
                                                   'tracked content is what the suites measure'))
    provenance = (before.get('provenance') or {}).get('kind', 'unknown')
    result['baseline'] = dict(kind=provenance,
                              complete=bool(before['suite']['summary'].get('complete')),
                              named_cases=len(before['suite']['summary']['cases']),
                              ran=before['suite']['summary'].get('ran'))
    if provenance != 'original-capture' or not result['baseline']['complete']:
        result['informational'].append(
            dict(code='baseline_partial',
                 detail=f"baseline kind {provenance}, "
                        f"{result['baseline']['named_cases']}/{result['baseline']['ran']} cases named"))
    return result


def ledger_verdict(ledger, before, after, diff, comp, signatures):
    """Three-state closure for one ledger, with machine-readable reasons and supporting test IDs."""
    reasons = []
    original = [case for case in before['suite']['summary']['cases'].values()
                if any(_ledger_of(signature) == ledger for signature in case.get('signatures', []))]
    recovered = [record for record in diff['recovered']
                 if any(_ledger_of(signature) == ledger for signature in record['before_signatures'])]
    still_failing = [case for case in after['suite']['summary']['cases'].values()
                     if case['outcome'] in BAD
                     and any(_ledger_of(signature) == ledger for signature in case.get('signatures', []))]
    guards = [case for case in after['suite']['summary']['cases'].values()
              if case['outcome'] == 'passed'
              and any(re.search(signature.get('guard_test_pattern', '(?!)'), case['test_id'], re.I)
                      for signature in signatures if signature['ledger'] == ledger)]

    state = 'inconclusive'
    if comp['blockers']:
        reasons.append(dict(code='captures_incomparable',
                            detail=', '.join(blocker['code'] for blocker in comp['blockers'])))
    if still_failing:
        state = 'failed'
        reasons.append(dict(code='ledger_signature_after',
                            detail=f'{len(still_failing)} failure(s) still carry a {ledger} signature'))
    if diff['disappeared']:
        state = 'failed'
        reasons.append(dict(code='disappeared_tests',
                            detail='a disappeared test is never a fix: '
                                   + ', '.join(record['test_id'] for record in diff['disappeared'][:5])))
    if diff['new_failures']:
        state = 'failed' if state == 'failed' else 'inconclusive'
        reasons.append(dict(code='new_failures',
                            detail=f'{len(diff["new_failures"])} test(s) fail that did not before'))
    if state != 'failed':
        if original:
            if len(recovered) == len(original):
                state = 'closed'
                reasons.append(dict(code='original_failures_recovered',
                                    detail=f'{len(recovered)}/{len(original)} named {ledger} failures now pass'))
            else:
                reasons.append(dict(code='original_failures_outstanding',
                                    detail=f'{len(recovered)}/{len(original)} named {ledger} failures recovered'))
        elif guards:
            state = 'closed'
            reasons.append(dict(code='positive_guard_evidence',
                                detail=f'{len(guards)} named {ledger} guard test(s) pass; '
                                       'no original failure was separately observable'))
        else:
            reasons.append(dict(code='no_evidence',
                                detail=f'no original {ledger} signature failure and no matching guard test'))
    reasons.append(dict(code='baseline_partial',
                        detail=f"baseline kind {comp['baseline']['kind']} with "
                               f"{comp['baseline']['named_cases']}/{comp['baseline']['ran']} cases named; "
                               'unrecorded failures cannot be attributed'))
    reasons.append(dict(code='health_semantics_unverified',
                        detail='base_health/extension_summary exited 0, but their semantics are host-owned'))
    return dict(ledger=ledger, state=state, reasons=reasons,
                original_failures=[case['test_id'] for case in original],
                recovered_tests=[record['test_id'] for record in recovered],
                still_failing_tests=[case['test_id'] for case in still_failing],
                guard_tests=[case['test_id'] for case in guards])


def assess(before, after, diff, signatures):
    comp = comparability(before, after)
    ledgers = {ledger: ledger_verdict(ledger, before, after, diff, comp, signatures) for ledger in LEDGERS}
    return dict(
        schema=REPORT_SCHEMA,
        evidence_a=diff,
        evidence_b=dict(base_health_before=before.get('base_health'),
                        base_health_after=after['base_health'],
                        extension_summary_before=before.get('extension_summary'),
                        extension_summary_after=after['extension_summary'],
                        captured_at=after.get('captured_at'),
                        health_correlation=after.get('health_correlation')),
        comparability=comp,
        verdict=dict(ledgers=ledgers,
                     evidence_satisfied=all(v['state'] == 'closed' for v in ledgers.values()),
                     tested_commit=(after.get('git') or {}).get('sha'),
                     captured_clean=(after.get('git') or {}).get('dirty') is False,
                     merge_authorized=False, authority='human',
                     note='evidence_satisfied describes the recorded evidence; it grants no permission'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', type=Path)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--after', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--suite-command', nargs='+',
                        default=[sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'])
    parser.add_argument('--signatures', type=Path, default=SIGNATURE_FILE)
    parser.add_argument('--ledger', type=Path,
                        help='optional: append this report to a tamper-evident audit ledger')
    parser.add_argument('--provenance-kind', default='original-capture',
                        help='label a capture: original-capture, or historical-partial when reconstructed')
    args = parser.parse_args()
    if args.capture:
        if not args.host or not (args.host / 'tests').is_dir():
            parser.error('capture requires --host with a tests directory')
        data = snapshot(args.host.resolve(), args.timeout, args.suite_command,
                        load_signatures(args.signatures), args.provenance_kind)
        args.capture.parent.mkdir(parents=True, exist_ok=True)
        args.capture.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        print('Captured', args.capture, 'tests', data['suite']['summary']['ran'],
              'errors', data['suite']['summary']['errors'],
              'complete', data['suite']['summary']['complete'],
              'sha', (data['git'].get('sha') or 'unknown')[:7])
        return 0
    if not args.after:
        parser.error('provide --capture or --after')
    after = json.loads(args.after.read_text(encoding='utf-8'))
    if not args.before:
        print(json.dumps({'verdict': {'evidence_satisfied': False, 'merge_authorized': False,
                                      'authority': 'human',
                                      'reasons': [{'code': 'baseline_absent',
                                                   'detail': 'no --before capture: nothing to attribute'}]}},
                         indent=2))
        return 2
    before = json.loads(args.before.read_text(encoding='utf-8'))
    diff = compare(before, after)
    report = assess(before, after, diff, load_signatures(args.signatures))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if args.ledger:
        # Optional plugin. The record is audit history; recording a verdict never authorizes a merge.
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            import ledger_plugin
            record = ledger_plugin.record_gate_report(report, args.ledger)
            print('Appended to ledger', args.ledger, 'sequence', record['sequence'],
                  'signature', 'ed25519' if record.get('signature') else 'none')
        except Exception as error:
            print('ledger append failed:', error, file=sys.stderr)
    print(json.dumps({ledger: dict(state=verdict['state'],
                                   reasons=[reason['code'] for reason in verdict['reasons']])
                      for ledger, verdict in report['verdict']['ledgers'].items()}
                     | dict(evidence_satisfied=report['verdict']['evidence_satisfied'],
                            merge_authorized=report['verdict']['merge_authorized']), indent=2))
    return 0 if after['suite']['summary']['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
