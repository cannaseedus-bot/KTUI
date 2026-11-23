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
| F14 | Registry owns exactly one schema (base fix) | **erased ×2** | `core/registry.py`, `core/assemble.py` |
| M1 | Re-apply F14 after the v3.4/v3.5 merge | open | `core/extension.py` or `load_directory` |
| M2 | Graph-level field declarations (`directed`, `data`, `overlap_policy`, `coverage_policy`) | open | `schemas/tensor-registry.gml`, `core/registry.py` |
| M3 | Keep `extension_contract()` reading the GML document, not a Python class | guard | `phases.py` |
| M4 | Confirm `gml_*` functions still run after the merge | open | `functions.py` |
| M5 | Full base suite green before merging to `main` | open | `kuhul-phase-engine-v0.1.0/tests` |
| M6 | Keep `-text` for the package in `.gitattributes` (digest integrity) | guard | `.gitattributes` |
| M7 | Mirror this task list into `task-list.json` through the bus, if wanted | open | `task_list.py` |

---

## Fixes that must survive a merge

### Base package (`kuhul-phase-engine-v0.1.0`)

**F14 — a registry owns exactly one schema.** `load_directory` validated *every* document in
`contracts/`, including other extensions' (`aiml-gml/1`, `gml-math/1`). Consequence: `setUp` raised
`registry.RegistryError: schema mismatch` and 30 of 48 tests errored.

- Fix: a schema-ownership predicate (`accepts(doc, registry)` / `Extension.schema_id`) gates
  validation in `load_directory`; `validate_document` still refuses a foreign schema when called
  directly, so the boundary is explicit.
- Verify: `cd kuhul-phase-engine-v0.1.0 && python -m unittest discover -s tests` → green.
- If erased: every test that builds fixtures via `load_directory` dies at `setUp`, and the count
  jumps from 0 to ~30 errors. This has happened twice.

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

**M2 — graph-level fields are still undeclared (open P3 gap).** `tensor` and `tensor.shape` reject
unknown attributes, but `data`, `coverage_policy`, `overlap_policy` and `directed` live at graph
level and are not declared, so `data [ vaule 1.0 ]` passes silently. Patch:

```gml
  field [ path "graph" name "directed"        type "integer" required 0 ]
  field [ path "graph" name "data"            type "block"   required 0 ]
  field [ path "graph" name "overlap_policy"  type "enum" values "reject" required 0 ]
  field [ path "graph" name "coverage_policy" type "enum" values "complete,sparse" required 0 ]
```

plus a graph-level allowlist in `validate_document` (`schema, contract, graph_id, tensor, slice` +
declared graph fields) and a `required` check in `load_registry` so deleting one fails closed at
bootstrap. Tests: typo in `data` → `unregistered field: data.vaule`; `coverage_policy "sparse"`
stays legal.

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

- The base suite is red (67 tests, 31 errors) in the middle of the v3.4/v3.5 merge; the host is
  deliberately decoupled from it and reports that state instead of inheriting it.
- M2 (graph-level declarations) is not landed — P3 holds for `tensor`/`tensor.shape` only.
- `gml-tensor/1` is not self-hosting: its registry is a GML document validated by handwritten code.
- No off-machine backup beyond GitHub; `main` was force-pushed once, so old clones must re-fetch.
