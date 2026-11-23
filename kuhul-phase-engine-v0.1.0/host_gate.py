#!/usr/bin/env python3
"""Read-only host evidence collector. Never authorizes merging."""
import argparse
import os
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

SIGNATURE_FILE = Path(__file__).with_name('signatures.json')
BAD = {'failed', 'errored'}

def run(cmd, cwd, timeout):
    # Captured output must be lossless: the child prints with the host locale unless told
    # otherwise, and decoding cp1252 bytes as utf-8 replaces '·' with U+FFFD in the evidence.
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                           env=env, timeout=timeout, errors='replace')
        return dict(command_line=cmd, exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr, timed_out=False)
    except subprocess.TimeoutExpired as exc:
        def decode(v):
            return v.decode('utf-8', 'replace') if isinstance(v, bytes) else (v or '')
        return dict(command_line=cmd, exit_code=None, stdout=decode(exc.stdout), stderr=decode(exc.stderr), timed_out=True)

def git_sha(host):
    r = run(['git', 'rev-parse', 'HEAD'], host, 15)
    return r['stdout'].strip() if r['exit_code'] == 0 else None

def load_signatures(path=SIGNATURE_FILE):
    entries = json.loads(Path(path).read_text(encoding='utf-8'))['signatures']
    ids = set()
    for item in entries:
        if item['id'] in ids or item['ledger'] not in ('F14', 'M2'):
            raise ValueError('duplicate or unknown signature declaration')
        ids.add(item['id'])
        re.compile(item['error_pattern'], re.I)
        re.compile(item['traceback_pattern'], re.I)
    return entries

def classify(error_type, traceback, signatures):
    return [s['id'] for s in signatures if re.search(s['error_pattern'], error_type or '', re.I)
            and re.search(s['traceback_pattern'], traceback or '', re.I)]

# A test with a docstring prints its name, a newline, the docstring, then the status. Without this
# join those tests vanish from the capture and `summary.complete` is false, which makes every later
# attribution inconclusive. Four tests in this checkout were being lost this way.
SPLIT_VERBOSE = re.compile(
    r'^(?P<id>.+? \([^()]+\))\s*\n(?P<doc>.*?) \.\.\. '
    r'(?P<status>ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)\s*$', re.M)

def normalise(text):
    """Join the docstring-split verbose form back into one line, so per-test capture is complete."""
    return SPLIT_VERBOSE.sub(lambda m: f"{m.group('id')} ... {m.group('status')}", text)

def parse_suite(result, signatures):
    output = normalise(result['stdout'] + '\n' + result['stderr'])
    cases = {}
    outcomes = {'ok':'passed','FAIL':'failed','ERROR':'errored', 'expected failure':'xfailed',
                'unexpected success':'failed'}
    for line in output.splitlines():
        m = re.match(r'^(.+?) \(([^()]+)\) \.\.\. (ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)\s*$', line.strip())
        if m:
            raw = m.group(3)
            outcome = 'skipped' if raw.startswith('skipped') else outcomes[raw]
            cases[m.group(2) + '.' + m.group(1)] = dict(test_id=m.group(2)+'.'+m.group(1),outcome=outcome,
                                                          error_type=None,traceback_head=None,traceback='',signatures=[])
    # unittest emits one traceback block per failing test, with an exact test ID.
    header = re.compile(r'^={5,}\n(?:FAIL|ERROR): (.+?) \(([^()]+)\)\n-{5,}\n', re.M)
    matches = list(header.finditer(output))
    for i, match in enumerate(matches):
        block = output[match.end(): matches[i+1].start() if i+1 < len(matches) else len(output)]
        block = re.split(r'\n-{5,}\nRan \d+ tests?', block, maxsplit=1)[0]
        test_id = match.group(2)+'.'+match.group(1)
        outcome = 'errored' if output[match.start():match.end()].find('ERROR:') >= 0 else 'failed'
        lines = block.strip().splitlines()
        exception_line = next((line.strip() for line in reversed(lines) if re.match(r'^[\w.]+(?:Error|Exception|Failure):',line.strip())), '')
        frame = next((line.strip() for line in lines if line.strip().startswith('File ')), '')
        error_type = exception_line.split(':',1)[1].strip() if ':' in exception_line else exception_line
        cases[test_id] = dict(test_id=test_id,outcome=outcome,error_type=error_type,
                              traceback_head=frame,traceback=block,signatures=classify(error_type,block,signatures))
    count = re.search(r'Ran (\d+) tests?',output)
    errors = re.search(r'errors=(\d+)',output)
    failures = re.search(r'failures=(\d+)',output)
    return dict(cases=cases,ran=int(count.group(1)) if count else None,
                errors=int(errors.group(1)) if errors else 0,
                failures=int(failures.group(1)) if failures else 0,
                ok=result['exit_code']==0 and bool(re.search(r'^OK\s*$',output,re.M)),
                complete=bool(count) and len(cases)==int(count.group(1)))

def snapshot(host, timeout, command, signatures):
    suite = run(command,host,timeout)
    health = run([sys.executable,'-c','import phases; print(phases.base_health())'],host.parent,timeout)
    summary = run([sys.executable,'-c','import phases; print(phases.extension_summary())'],host.parent,timeout)
    return dict(captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                git_sha=git_sha(host),host=str(host),command_line=command,
                signature_declarations=signatures,
                suite=dict(run=suite,summary=parse_suite(suite,signatures)),
                base_health=health,extension_summary=summary)

def compare(before,after):
    b = before['suite']['summary']['cases']; a = after['suite']['summary']['cases']
    recovered=[]; disappeared=[]; new_failures=[]; unchanged=[]; changed=[]
    for name in sorted(set(b)|set(a)):
        old=b.get(name); new=a.get(name)
        record=dict(test_id=name,before=old['outcome'] if old else 'absent',after=new['outcome'] if new else 'absent',
                    before_signatures=old.get('signatures',[]) if old else [],
                    after_signatures=new.get('signatures',[]) if new else [])
        if old and old['outcome'] in BAD and new and new['outcome']=='passed': recovered.append(record)
        elif old and not new: disappeared.append(record)
        elif new and new['outcome'] in BAD and (not old or old['outcome'] not in BAD): new_failures.append(record)
        elif old and new and old['outcome']==new['outcome']: unchanged.append(record)
        else: changed.append(record)
    matched={s['id']:[] for s in before['signature_declarations']}
    unmatched=[]
    for record in recovered:
        if record['before_signatures']:
            for signature in record['before_signatures']: matched.setdefault(signature,[]).append(record['test_id'])
        else: unmatched.append(record['test_id'])
    return dict(recovered=recovered,recovered_matched=matched,recovered_unmatched=unmatched,
                disappeared=disappeared,new_failures=new_failures,unchanged=unchanged,changed=changed)

def assess(before,after,diff):
    reasons=[]
    if not before or not diff:
        reasons.append('original baseline unavailable')
    else:
        if before['host']!=after['host']: reasons.append('different host paths')
        if before['command_line']!=after['command_line']: reasons.append('different suite commands')
        if before['signature_declarations']!=after['signature_declarations']: reasons.append('signature declarations changed')
        if not before['suite']['summary']['complete'] or not after['suite']['summary']['complete']:
            reasons.append('incomplete per-test capture')
        if diff['disappeared']: reasons.append('tests disappeared: '+', '.join(r['test_id'] for r in diff['disappeared']))
        if diff['new_failures']: reasons.append('new failing tests present')
    if not after['suite']['summary']['ok']: reasons.append('host suite not green')
    if after['base_health']['exit_code']!=0: reasons.append('base_health command failed')
    if after['extension_summary']['exit_code']!=0: reasons.append('extension_summary command failed')
    # Host-defined outputs have no machine-verifiable health schema here.
    reasons.append('base_health and extension_summary semantic health not independently verified')
    result={}
    for ledger in ('F14','M2'):
        recovered=[r for r in (diff or {}).get('recovered',[]) if any(s.startswith(ledger+'-') for s in r['before_signatures'])]
        original=[r for r in (before or {}).get('suite',{}).get('summary',{}).get('cases',{}).values()
                  if any(s.startswith(ledger+'-') for s in r.get('signatures',[]))]
        specific=list(reasons)
        if not original: specific.append(f'no original named {ledger} signature failures')
        if original and len(recovered)!=len(original): specific.append(f'not all original {ledger} signature failures recovered')
        result[ledger.lower()+'_closed']=dict(status='inconclusive' if specific else 'evidence_satisfied',reasons=specific,
                                             matched_recovered=[r['test_id'] for r in recovered])
    return dict(evidence_a=diff,evidence_b=dict(base_health_before=before.get('base_health') if before else None,
                base_health_after=after['base_health'],extension_summary_before=before.get('extension_summary') if before else None,
                extension_summary_after=after['extension_summary']),verdict={**result,'merge_authorized':False})

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',type=Path)
    parser.add_argument('--capture',type=Path)
    parser.add_argument('--before',type=Path)
    parser.add_argument('--after',type=Path)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--timeout',type=int,default=180)
    parser.add_argument('--suite-command',nargs='+',default=[sys.executable,'-m','unittest','discover','-s','tests','-v'])
    parser.add_argument('--signatures',type=Path,default=SIGNATURE_FILE)
    args=parser.parse_args()
    if args.capture:
        if not args.host or not (args.host/'tests').is_dir(): parser.error('capture requires --host with tests directory')
        data=snapshot(args.host.resolve(),args.timeout,args.suite_command,load_signatures(args.signatures))
        args.capture.parent.mkdir(parents=True,exist_ok=True)
        args.capture.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
        print('Captured',args.capture,'tests',data['suite']['summary']['ran'],'errors',data['suite']['summary']['errors'])
        return 0
    if not args.after: parser.error('provide --capture or --after')
    after=json.loads(args.after.read_text(encoding='utf-8'))
    before=json.loads(args.before.read_text(encoding='utf-8')) if args.before else None
    diff=compare(before,after) if before else None
    report=assess(before,after,diff)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['verdict'],indent=2))
    return 0 if after['suite']['summary']['ok'] else 2

if __name__=='__main__': raise SystemExit(main())
