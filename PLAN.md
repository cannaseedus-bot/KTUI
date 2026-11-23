# PLAN — regression ledger and task list

This file exists because fixes kept getting erased. The K'UHUL base is rewritten continuously
(`kuhul-phase-engine-v0.1.0` was rewritten three times in ten minutes on one occasion), and each
rewrite silently dropped a fix that the host or the suite depended on. A commit message is not a
place to keep an invariant; this file is.

Rules for using it:

1. Every entry states **symptom → fix → how to verify → what breaks if erased**. An entry without a
   verification command is a wish, not a fix.
2. Never delete an entry because the code "looks fine now". Delete it only when a test enforces it.
3. After any merge of the base (v3.4, v3.5, …), run § Merge checklist before committing.
4. New entries go at the end of their section with the next free ID.

---

## Task list

Status: `done` = in the tree and verified · `guard` = enforced by a test · `open` = not landed yet

| ID | Task | Status | Where |
|---|---|---|---|
| F1 | Repo-root path anchoring (nothing writes one directory up) | done | `gpt-oss.toml`, `task_list.py`, `interaction_log.py`, `task-engine.py` |
| F2 | Serve from the repo-local `runtime/llama` build | done | `gpt-oss.toml` |
| F3 | Speed dial: `[models]` ordered fastest → deepest, one order everywhere | guard | `gpt-oss.toml`, `chat_app.py`, `task-engine.py` |
| F4 | Any model can be made the default, surgically | guard | `model_config.py`, `/default`, `task-engine.py default` |
| F5 | Launcher: health wait, model menu, `stop`, `keys`, `advisor` | done | `start.bat` |
| F6 | Cloud advisors with clickable key pages; Anthropic included | done | `chat_app.py` (`KEY_PAGES`), `start.bat` |
| F7 | Session transcripts: `/sessions`, `/resume`, `/rewind`, `/new` | guard | `session_log.py`, `chat_app.py` |
| F8 | Workspace picker + read-only default + `/allow` grant | guard | `chat_app.py` (`Sandbox`, `WorkspacePicker`) |
| F9 | AIML tool bridge (`TOOL <verb>` / `__LLM_FALLBACK__`) | guard | `_override.aiml`, `chat_app.py` |
| F10 | Typed function registry + plan admission | guard | `functions.py`, `planner.py`, `plans.toml` |
| F11 | Daemon engine: six-phase cycle per turn + 69 mode vectors | done | `daemon.py`, `chat_app.py` |
| F12 | Phase package adapter: digest-gated banks, contract order, collisions | guard | `phases.py`, `.gitattributes` |
| F13 | GML functions, `gml_audit` plan, `/gml` | done | `functions.py`, `plans.toml`, `chat_app.py` |
| F14 | Registry owns exactly one schema; foreign documents are not ours to validate | **guard** | `core/extension.py` (`owns_document`), `tests/test_merge_guards.py`, `tests/test_registry_v3.py` |
| M1 | Re-apply F14 after the v3.4/v3.5 merge | **done** | `core/extension.py`, `core/assemble.py` |
| M2 | Graph-level and `data.value` declarations; unknown fields fail closed | **guard** | `schemas/tensor-registry.gml`, `core/registry.py`, `tests/test_merge_guards.py`, `tests/test_declaration_guards.py` |
| M3 | Keep `extension_contract()` reading the GML document, not a Python class | guard | `phases.py` |
| M4 | Confirm `gml_*` functions still run after the merge | **done** | `functions.py` (verified after v3.5) |
| M5 | Full base suite green before merging to `main` | **done** | `kuhul-phase-engine-v0.1.0/tests` — 74 tests, OK |
| M6 | Keep `-text` for the package in `.gitattributes` (digest integrity) | guard | `.gitattributes` |
| M7 | Mirror this task list into `task-list.json` through the bus, if wanted | open | `task_list.py` |

---

## Last verified

```
kuhul-phase-engine-v0.1.0: python -m unittest discover -s tests   ->  Ran 74 tests, OK
base_health    : banks 9 · categories 238 · bad digests 0 · missing modules none
extension      : gml-tensor/1 owned by gml.tensor · fields 19 over data, graph, slice, tensor,
                 tensor.shape · constraints 6 · operator ASSEMBLE
gml_validate   : col_a STRUCTURALLY_VALIDATED · assembled STRUCTURALLY_VALIDATED ·
                 category OUT_OF_SCOPE (aiml-gml/1)
gml_assemble   : tensor/assembled shape=(6, 2) dtype=float32 coverage=12/12 (plan only)
gml_audit      : admitted and run through the planner
```

Merge order used: **F14 → M2 → base suite → `base_health()` → `extension_summary()` → host tools**.

## Fixes that must survive a merge

### Base package (`kuhul-phase-engine-v0.1.0`)

**F14 — a registry owns exactly one schema.** Landed in the v3.5 form: `core/extension.py` exposes
`owns_document(extension, doc)` and `load_directory` skips documents that are not ours; a misspelled
or foreign schema is therefore *not* validated under the wrong contract. `validate_document` still
refuses a foreign document when called directly, so the boundary is enforced, not merely tolerated.

- Guards: `tests/test_merge_guards.py` (loader skips, ownership predicate is the gate) and
  `tests/test_registry_v3.py::test_registry_validates_all_sources` (asserts both sides — owned
  documents validate, a foreign one raises `schema mismatch`).
- Erased twice before this landed; if it vanishes again the signature is ~30 errors at `setUp`.

**M2 — graph-level and `data.value` declarations.** Landed in two layers, and both need a guard
because tightening one without the other is silent:

1. *Document side* (`core/registry.py`): graph-level attributes are allowlisted and typed, `data`
   entries must be `value`, and repeated `value` entries stay legal (`len>1` is refused for every
   field **except** `data.value`). Guards: `test_merge_guards.py` — `vaule`, `directde`, and an
   invalid `coverage_policy` enum are all rejected.
2. *Declaration side* (`load_registry`): the graph-level and `data.value` declarations are in the
   bootstrap `required` set, so deleting one fails at load time instead of leaving every document to
   fail later as "unregistered field". Guards: `tests/test_declaration_guards.py` — removing the
   `coverage_policy` declaration, removing the `data.value` declaration, and a repeated-value
   document that must keep validating.

**B2 — dtype is widened, the mismatch guard is reachable.**
`float32,float64` are both registered; a lone float64 source + float64 assembly is legal and
materialises, while a *mix* fails with both sides named:
`dtype mismatch: assembly float64, source tensor/col_a float32`.
If someone re-narrows the enum to `float32`, the guard becomes dead code again and
`test_dtype_mismatch_public_path` fails.

**B3 — the registry names all six constraints.** `data_count`, `finite_values`, `dtype_match`,
`bounds_check`, `no_overlap`, `complete_coverage`, each with `predicate`, `arity`, `scope` and
`authority "declaration_only"`, dispatched through `rules.check`. The callsite-`require` tests
(v3.3) are what keep the registry from drifting into decoration — a `check(...)` added without a
declaration must fail.

**M2 — graph-level fields (was open, now landed).** `tensor` and `tensor.shape` reject unknown
attributes, and so do graph-level attributes and `data.value` (see above). The registry declares
`directed`, `data`, `overlap_policy`, `coverage_policy` and `value`; a typo is a rejection, and the
bootstrap `required` set keeps the declarations from disappearing.

**M6 — keep the package's bytes raw.** `.gitattributes` carries
`kuhul-phase-engine-v0.1.0/** -text`. The manifest's SHA-256 digests cover CRLF files as delivered;
normalising line endings on commit silently invalidates all nine digests and the host stops trusting
every phase bank. Verify: `python -c "import phases; print(phases.verify()['bad_digest'])"` → `[]`.

### Host python (`chat_app.py` and friends)

**H1 — nothing executes without admission.** `functions.py` declares each callable's types,
authority and handler; `planner.py` admits a composition only when every step is registered,
implemented, type-chained and argument-complete; `run()` requires `authority = "execute"`. AIML may
*propose*; the registry admits. If this is relaxed, a template becomes a capability the host does
not have — `weather_report` is the standing example of a plan that must stay refused.

**H2 — every turn runs the six phases.** `daemon.Daemon.run` records Pop → Wo → Yax → Sek → Ch'en →
Xul, in the order `registry/phase-contract.json` declares. A similarity match may only ever select a
**read-only** verb (`git`, `time`, `convert`, `files`); writes are never selectable that way, and
`admit_verb`/`admit_plan` are the gates. `/daemon` shows the trace.

**H3 — the base is read, not assumed.** `phases.extension_contract()` parses
`schemas/tensor-registry.gml`; `phases.core_module()` imports a core module on demand;
`base_health()` reports banks, digests, missing modules and the newest edit. Do not replace these
with an import of a `Registry` class: that API has changed shape repeatedly.

**H4 — the security fix nobody should undo.** `Sandbox.run_command` enforces the **per-subcommand**
allowlist, mirroring the terminal. Before this, `git push` and friends ran with only the program
name checked. Verify: `git_command` with `push` → `git needs one of: branch, describe, diff, grep,
log, ls-files, rev-parse, show, status`.

**H5 — writes are a grant, not a default.** `write_file`/`patch_file` are offered to the model only
while `/allow` is on; choosing a different workspace resets to read-only; `.git`, `logs`,
`node_modules`, `dist`, `.env*` stay blocked; 200 KB cap; ambiguous patches are refused.

**H6 — sessions are files, not memory.** `logs/sessions/<id>.jsonl`, rewritten from memory on
rewind/resume so a torn line cannot desync. `search_history` is read-only and bounded. `VerticalScroll`
has no `clear()` — use `remove_children()` (this crashed `/clear` before it was fixed).

**H7 — AIML answers first, honestly.** `_override.aiml` returns `TOOL <verb>` (executed by the host)
or `__LLM_FALLBACK__` (handed to the model). Weather and translation fall back on purpose; never
invent tool output for them.

**H8 — the model is told what it has.** The system brief lists the workspace, the permission mode,
every tool with the phrasing it answers, and the daemon mode prior. It is refreshed on
`/workspace` and `/allow`. A model cannot call what it cannot name.

### Repo, launcher and git

**F1 — one root, no `..`.** Everything resolves from the directory holding `gpt-oss.toml`; `root = "."`.
A `parents[1]` anywhere means files land in the user profile.

**F5 — the launcher waits.** `start.bat` starts `llama-server` in its own window, polls `/health`, then
opens the app; `stop` kills only that server; a server already answering is reused.

**F6 — secrets stay local.** `.env` is gitignored *and* on the sandbox blocklist; `start.bat advisor`
types the key hidden and writes it with PowerShell (visible fallback when there is no console).

**R-git — this checkout's git needs two local settings.** `http.sslBackend=openssl` (schannel fails
with `SEC_E_NO_CREDENTIALS` here) and a `.git/gh-cred.cmd` credential helper calling
`gh auth git-credential` (the `!gh …` form dies in `sh.exe`). Pushes used an `AUTHORIZATION: basic`
header. The remote's pre-recovery history is preserved as branch `backup/origin-main`.

---

## Merge checklist (run after every base merge)

```bat
:: 1. the base's own suite must be green before anything is merged
cd kuhul-phase-engine-v0.1.0
python -m unittest discover -s tests
::    expect: "OK" (67 tests and growing); errors usually mean the F14 schema gate was dropped

:: 2. the host still trusts the banks (digests untouched by core/ edits)
cd ..
python -c "import phases; print(phases.base_health())"
::    expect: bad digests 0, missing modules none

:: 3. the extension contract is still readable from the document
python -c "import phases; print(phases.extension_summary())"
::    expect: GML extension `gml-tensor/1` … constraints: 6 … operator ASSEMBLE

:: 4. the GML functions and their plan
python -c "import functions,planner; from pathlib import Path; print(planner.run(planner.resolve('gml_audit'), functions.ToolContext(Path('.')))[1][:200])"

:: 5. the daemon and the AIML banks
python chat_app.py     :: then: git status · what changed · find aiml categories git status · /phase · /gml · /daemon
```

Expected failure signatures and what they mean:

| Symptom | Cause | Fix |
|---|---|---|
| `schema mismatch` in many `setUp`s | F14 schema gate removed | re-apply `accepts()` in `load_directory` |
| `bad digests 9` | package bytes normalised by git | restore `-text` in `.gitattributes` |
| `missing modules: extension` | base renamed a core module | update `phases.CORE_MODULES` |
| `ModuleNotFoundError: gml2` | core imported without `core/` on `sys.path` | use `phases.core_module()` |
| plan refused: "no handler" | new function declared but unimplemented | implement it, or keep the plan proposal-only |

---

## Known gaps at the time of writing

- `gml-tensor/1` is not self-hosting: its registry is a GML document validated by handwritten,
  dispatch-declared rules. The ledger entries above are how that stays honest until it is.
- The AIML side of the package (v3.5 `core/aiml_bundle.py`, `tests/test_aiml_port.py`) is newer than
  the host's use of it: the host reads the phase banks and the extension contract, not the bundle.
- `M7` is optional: the task list lives here, and `task-list.json` is rendered runtime state.
- No off-machine backup beyond GitHub; `main` was force-pushed once, so old clones must re-fetch.
