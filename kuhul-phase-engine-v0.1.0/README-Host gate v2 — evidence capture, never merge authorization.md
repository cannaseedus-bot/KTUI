# Host gate v2 — evidence capture, never merge authorization

Run from the host machine with the exact original suite invocation. The default is `python -m unittest discover -s tests -v`; if the original invocation differed, supply `--suite-command` identically for both captures.

```bat
python host_gate.py --host "C:\path\to\kuhul-phase-engine-v0.1.0" --capture before.json
REM Apply reviewed patch only after capturing before.json.
python host_gate.py --host "C:\path\to\kuhul-phase-engine-v0.1.0" --capture after.json
python host_gate.py --before before.json --after after.json --report host-gate-report.json
```

Captures include raw stdout/stderr, exact command, timestamp, git SHA, named unittest outcomes and per-case tracebacks, and verbatim host health commands. `signatures.json` is the declared failure-signature registry; matching is per-test and requires both an error pattern and traceback-location pattern. Unmatched recoveries and disappeared tests remain visible.

The report separates `evidence_a` (named tests) from `evidence_b` (raw health), with conservative closure assessments. Because `base_health()` and `extension_summary()` have host-defined semantics, this tool **never claims closure automatically** without a verified semantic contract. `merge_authorized` is always false.

The harness cannot reconstruct a baseline from aggregate counts. Captures are comparable only when their host paths, command lines, and signature declarations agree. A git SHA difference is expected across a patch, but preserve the before/after SHAs to audit exactly what changed. No source files or git settings are modified.

Run harness unit tests: `python -m unittest discover -p test_host_gate_v2.py -v`.
