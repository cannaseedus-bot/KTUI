# F14/M2 host diagnostic gate

Read-only runner. It **does not** apply patches, change git settings, or authorize a merge. Requires the actual `kuhul-phase-engine-v0.1.0` checkout to capture real results.

## Usage (Windows)

Run from any directory, substituting the real checkout path:

```bat
python host_gate.py --host "C:\path\to\kuhul-phase-engine-v0.1.0" --capture before.json
:: apply the patch using your normal reviewed merge workflow
python host_gate.py --host "C:\path\to\kuhul-phase-engine-v0.1.0" --capture after.json
python host_gate.py --before before.json --after after.json --report host-gate-report.json
```

The `before.json` must be captured **before** patching. The reported historic “67 tests, 31 errors” is not a substitute for test names and tracebacks. The tool records the complete `unittest -v` output, per-test status, F14/M2 signatures, `phases.base_health()` and `phases.extension_summary()` results. Comparison identifies recovered cases **by name**, not just count. If a test disappears it is marked `NOT_SEEN`, not counted as recovered.

## Merge requirements not inferred by this harness

- Confirm `base_health()` reports **bad digests 0** and **missing modules none**; exit code 0 alone is insufficient.
- Confirm `extension_summary()` reports `gml-tensor/1`, six constraints, and `ASSEMBLE`.
- Check M3 `extension_contract()` reads GML, M4 `gml_*`, M5 full suite, M6 `-text`, M7 `task-list.json` explicitly.
- Preserve F1–F13 guards, `Sandbox.run_command` subcommand allowlist, `/allow` write grant, `remove_children()` behavior, and checkout-specific git configuration.
- A `schema mismatch` disappearance is evidence only when the named F14 test also recovers; no signature match by itself is not proof.

The report always says `REVIEW_REQUIRED` until these host-specific requirements are checked by a maintainer. No result here authorizes merging to `main`.
