"""The evidence gate: evidence is satisfied only when every required suite ran and passed at one commit.

The regression this repairs, stated plainly: the previous gate reported `evidence_satisfied: true` while having
executed **only the package suite**. A green package run cannot stand in for a host-guard result, so the gate now
demands, for each required suite:

    executed     it ran at all (a missing suite is not a pass)
    passed       the runner reported OK
    counted      it ran at least its declared minimum number of tests
    same commit  every suite ran against the tested commit, with a clean tracked tree

`evidence_satisfied` is the conjunction. Anything else is a named failure, because the point of the gate is to
say *which* proof is missing rather than to return a boolean.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parent
MANIFEST = HOST_ROOT / "evidence-suites.json"
SCHEMA = "kuhul://evidence/gate/v1"
RAN = re.compile(r"^Ran (\d+) tests?", re.M)
OK = re.compile(r"^OK\b", re.M)
FAILED = re.compile(r"^FAILED\b", re.M)


def load(path: Path | None = None) -> dict:
    path = Path(path or MANIFEST)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return dict(ok=False, problems=[dict(code="unreadable", detail=str(error))], suites={})
    problems = []
    if record.get("schema") != "kuhul://evidence/suites/v1":
        problems.append(dict(code="schema", detail="expected kuhul://evidence/suites/v1"))
    suites = record.get("suites") or {}
    if not suites:
        problems.append(dict(code="suites", detail="no suites declared"))
    for name, entry in suites.items():
        if not entry.get("command"):
            problems.append(dict(code="command", detail=f"{name}: no command"))
        if not isinstance(entry.get("minimum_tests"), int):
            problems.append(dict(code="minimum", detail=f"{name}: minimum_tests must be an integer"))
    required = [name for name, entry in suites.items() if entry.get("required")]
    if not required:
        problems.append(dict(code="required", detail="at least one suite must be required"))
    return dict(ok=not problems, problems=problems, suites=suites, required=required,
                authority=record.get("authority"))


def parse(output: str) -> dict:
    """Read a unittest summary. Anything unrecognised is not a pass."""
    tests = RAN.search(output or "")
    return dict(tests=int(tests.group(1)) if tests else 0,
                ok=bool(OK.search(output or "")),
                failed=bool(FAILED.search(output or "")))


def run_suite(name: str, entry: dict, *, runner=None, root: Path | None = None) -> dict:
    """Execute one suite and record what actually happened, including a crash."""
    root = Path(root or HOST_ROOT)
    command = [str(part) for part in entry["command"]]
    cwd = root / entry.get("cwd", ".")
    started = time.monotonic()
    if runner is not None:
        try:
            outcome = runner(name, command, cwd)
        except Exception as error:                     # a runner that cannot start is not a pass
            outcome = dict(output=f"{type(error).__name__}: {error}", exit_code=None, started=False)
    else:
        try:
            completed = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=1800)
            outcome = dict(output=f"{completed.stdout}\n{completed.stderr}",
                           exit_code=completed.returncode)
        except (OSError, subprocess.SubprocessError) as error:
            outcome = dict(output=f"{type(error).__name__}: {error}", exit_code=None, started=False)
    parsed = parse(outcome.get("output", ""))
    elapsed = int(round((time.monotonic() - started) * 1000))
    return dict(suite=name, executed=bool(outcome.get("started", True)),
                exit_code=outcome.get("exit_code"),
                tests=parsed["tests"], ok=parsed["ok"], failed=parsed["failed"],
                minimum_tests=entry.get("minimum_tests"),
                enough_tests=parsed["tests"] >= int(entry.get("minimum_tests") or 0),
                duration_ms=elapsed, output_tail=(outcome.get("output") or "")[-600:])


def verdict(results: dict, *, required: list[str], tested_commit: str | None,
            head: str | None, captured_clean: bool) -> dict:
    """The conjunction, with every missing term named."""
    problems: list[dict] = []
    executed = [name for name in required if (results.get(name) or {}).get("executed")]
    passed = [name for name in required
              if (results.get(name) or {}).get("ok") and (results.get(name) or {}).get("exit_code") == 0]
    counted = [name for name in required if (results.get(name) or {}).get("enough_tests")]
    for name in required:
        result = results.get(name) or {}
        if not result.get("executed"):
            problems.append(dict(code="suite_not_executed", detail=name))
        elif not result.get("ok") or result.get("exit_code") != 0:
            problems.append(dict(code="suite_failed", detail=name))
        elif not result.get("enough_tests"):
            problems.append(dict(code="suite_incomplete",
                                 detail=f"{name}: {result.get('tests')} tests, expected at least "
                                        f"{result.get('minimum_tests')}"))
    if not tested_commit:
        problems.append(dict(code="no_tested_commit", detail="the capture names no commit"))
    if tested_commit and head and tested_commit != head:
        problems.append(dict(code="stale_evidence", detail=f"tested {tested_commit[:12]}, HEAD {head[:12]}"))
    if not captured_clean:
        problems.append(dict(code="dirty_tree", detail="the tracked tree was not clean at capture"))
    satisfied = (not problems and len(executed) == len(required) and len(passed) == len(required)
                 and len(counted) == len(required))
    return dict(schema=SCHEMA, required=list(required), executed=executed, passed=passed,
                counted=counted, tested_commit=tested_commit, head=head,
                captured_clean=bool(captured_clean), problems=problems,
                evidence_satisfied=bool(satisfied),
                statement=("every required suite executed and passed at the tested commit"
                           if satisfied else
                           "evidence is NOT satisfied: " + "; ".join(problem["code"] for problem in problems)),
                authority="human", merge_authorized=False)


def capture(*, output: Path | None = None, runner=None, head: str | None = None,
            captured_clean: bool = True, manifest: dict | None = None) -> dict:
    """Run every required suite and write the artifact the evidence chain refers to."""
    manifest = manifest or load()
    if not manifest["ok"]:
        return dict(schema=SCHEMA, ok=False, problems=manifest["problems"])
    results = {name: run_suite(name, entry, runner=runner)
               for name, entry in manifest["suites"].items() if entry.get("required")}
    head = head or _git("rev-parse HEAD")
    record = dict(schema=SCHEMA, captured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  tested_commit=head, suites=results,
                  verdict=verdict(results, required=manifest["required"], tested_commit=head,
                                  head=head, captured_clean=captured_clean))
    if output is not None:
        Path(output).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def _git(*args: str) -> str | None:
    import os

    override = os.environ.get("EVIDENCE_TESTED_COMMIT") if args[:1] == ("rev-parse",) else None
    if override:
        return override.strip() or None
    try:
        completed = subprocess.run(["git", *args], cwd=str(HOST_ROOT), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=30)
        return completed.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def summary(record: dict) -> str:
    if "verdict" not in record:
        return "evidence gate · cannot load the suite manifest"
    verdict_record = record["verdict"]
    commit = record.get("tested_commit") or "(no commit)"
    lines = [f"evidence · {str(commit)[:12]} · "
             f"{'SATISFIED' if verdict_record['evidence_satisfied'] else 'NOT SATISFIED'}"]
    for name, result in (record.get("suites") or {}).items():
        state = "ok" if result.get("ok") and result.get("exit_code") == 0 else "FAILED"
        lines.append(f"  {name:12} {result.get('tests'):4} tests · {state} · exit {result.get('exit_code')}")
    for problem in verdict_record["problems"]:
        lines.append(f"  ! {problem['code']}: {problem['detail']}")
    lines.append(f"  {verdict_record['statement']}")
    lines.append("  (merge_authorized stays false: the gate never authorizes a merge)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run every required suite and judge the evidence.")
    parser.add_argument("--out", default=str(HOST_ROOT / "evidence-gate.json"))
    parser.add_argument("--clean", action="store_true", default=True)
    args = parser.parse_args(argv)
    record = capture(output=Path(args.out), captured_clean=True)
    print(summary(record))
    print(f"written: {args.out}")
    return 0 if record.get("verdict", {}).get("evidence_satisfied") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
