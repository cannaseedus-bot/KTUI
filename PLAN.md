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
| F15 | F14.1: a document with **no** schema is malformed (rejected, not skipped); a foreign document **referenced** by a validated graph is refused | **guard** | `core/extension.py` (`owns_document`), `core/resolvers.py` (`expected_schema`), `core/assemble.py` |
| F16 | M2.1: `data.value` declared `repeatable 1`, other fields non-repeatable; validation errors name the scope (`graph.` vs `data.`) | **guard** | `schemas/tensor-registry.gml`, `core/registry.py` |
| M1 | Re-apply F14 after the v3.4/v3.5 merge | **done** | `core/extension.py`, `core/assemble.py` |
| M2 | Graph-level and `data.value` declarations; unknown fields fail closed | **guard** | `schemas/tensor-registry.gml`, `core/registry.py`, `tests/test_merge_guards.py`, `tests/test_declaration_guards.py` |
| M3 | `extension_contract()` reads the GML document, not a Python class | **guard** | `tests_host/test_host_guards.py::M3…` (edits a registry fixture, asserts the contract changes) |
| M4 | The `gml_*` functions stay registered and callable | **guard** | `tests_host/test_host_guards.py::M4…` (enumeration, imports, representative calls, gml_audit run) |
| M5 | The package suite is green **after** integration, every run | **guard** | `tests_host/test_host_guards.py::M5…` (runs the suite as a subprocess) |
| M6 | The `-text` rule survives, so manifest digests stay valid | **guard** | `tests_host/test_host_guards.py::M6…` (`git check-attr text` = unset, `bad_digest` empty) |
| M7 | The ledger is mirrored into `task-list.json` and agrees with it | **guard** | `mirror_ledger.py`, `tests_host/test_host_guards.py::M7…` (ids, status, note, idempotence, human tasks preserved) |
| M8 | Harness self-tests: v2.1 rules covered by 14 named tests | **guard** | `kuhul-phase-engine-v0.1.0/test_host_gate.py` |
| M9 | Gate evidence names the commit it tested and comes from a clean tree | **guard** | `tests_host/test_host_guards.py::M9…`; artifacts are committed **after** the code they test, so `tested_commit` is the artifact commit's parent |
| M10 | Optional audit ledger: append-only, hash-chained, Ed25519-signed records | **guard** | `ledger_plugin.py`, `ledger.gml`, `tests_host/test_ledger.py::M10…` |
| M11 | Independent, restorable backups whose restore is verified | **guard** | `backup.py`, `tests_host/test_backup.py::M11…` |
| M12 | User memory: AIML proposes, host admits, JSONL records, GML projects | **guard** | `user_memory.py`, `memory.gml`, `memory.aiml`, `tests_host/test_memory.py::M12…` |
| M13 | AIML bundle consumed as declarations: resolved proposals, zero authority | **guard** | `aiml_host.py`, `functions.py` (`aiml_bundle_validate`, `aiml_propose`), `tests_host/test_aiml_bundle_host.py::M13…` |
| M14 | The daemon introduces itself (not ALICE), lists its models and its mark; the mark is downsized | **guard** | `identity.aiml`, `chat_app.py` (`identity_text`), `logo.png`, `tests_host/test_identity_logo.py::M14…` |
| M15 | Routing honesty: refusals answer locally, every turn kind renders, model handoffs say why | **guard** | `daemon.py` (refused kind), `chat_app.py` (`routing_note`, headings), `tests_host/test_routing.py::M15…` |

---

## Host gate evidence (F14 / M2)

Two independent forms, as required — named test cases, then runtime health. Artifacts:
`host-gate-before-v2.json`, `host-gate-after-v2.json`, `host-gate-report.json`
(`host-gate-before.json` is the raw v1 baseline those were converted from).

**Evidence A — named recoveries.** 31 tests named as failing before, 31 passing after.

```
recovered           : 31   (30 classified F14-schema-mismatch, 1 unmatched)
disappeared         : 0
new failures        : 0
unchanged           : 0
recovered_unmatched : test_contracts.Contracts.test_structural   (V-schema reason, not F14)
```

**Evidence B — runtime health.** `base_health` and `extension_summary` both exit 0 after the merge:

```
banks 9 · categories 238 · bad digests 0 · missing modules none
GML extension `gml-tensor/1` owned by gml.tensor · registry bootstrap `gml-registry/1`
```

**v2.1 verdicts — three states, evidence separated from authority:**

```
F14 : closed      reasons original_failures_recovered, baseline_partial, health_semantics_unverified
                  30 recovered · 6 guard tests · 0 still failing
M2  : closed      reasons positive_guard_evidence, baseline_partial, health_semantics_unverified
                  10 named guard tests pass · no original M2 failure was separately observable
evidence_satisfied: true      merge_authorized: false      authority: human
comparability: no blockers · informational: sha_changed, working_tree_dirty, baseline_partial
```

That is the dead end removed: `evidence_satisfied` now describes the recorded evidence and is
reachable, while `merge_authorized` stays false unconditionally. The three reasons above are
deliberate caveats, not failures:

1. `baseline_partial` — 31 failing names were retained, the 17 passing names of that 48-test run were
   not, so the baseline is labelled `historical-partial (31/48)` and never padded with invented
   cases. A fully attributable cycle needs a v2.1 capture taken *before* the patch.
2. `health_semantics_unverified` — `base_health` and `extension_summary` exit 0 and their text is
   captured verbatim, but their semantics are host-owned; the tool says so instead of pretending.
3. `sha_changed` / `working_tree_dirty` are recorded as informational: applying a patch moves the
   commit, and a capture of a dirty tree is still evidence.

**v2.1 capture hygiene** (the contract that made the above possible): every capture records the exact
invocation and interpreter, git SHA + branch + working-tree status, timestamps and suite duration,
and whether the health commands ran in the same invocation as the suite
(`health_correlation.same_run`). Comparability compares invocation, host and signature table; SHA
moves are informational, never rejections.

**Does the harness deliver the seven properties it claims?** Audited against the code, with the
report as evidence:

| Claim | Holds | How it is enforced |
|---|---|---|
| Declared signatures | yes | `signatures.json`, validated at load: duplicate ids, unknown ledger, and both patterns are compiled |
| Named test evidence | yes* | per-test `outcome` + `traceback` block, keyed by qualified id; *was incomplete until the docstring fix below |
| F14/M2 attribution | yes | `classify(error_type, block, signatures)` runs on **each failure's** block, never the whole log |
| Unmatched recoveries | yes | `recovered_unmatched` — this run reports `test_contracts.test_structural` rather than claiming it |
| Disappeared ≠ fixed | yes | `recovered` requires `after == passed`; an absent test lands in `disappeared` (0 here) |
| Runtime health captured independently | yes* | separate `run()` results for `base_health` and `extension_summary`; *was lossy until the decoding fix below |
| Closure conservative, merge never authorized | yes | `assess()` appends the health-semantics reason unconditionally; `merge_authorized: false` |

**Two harness defects found and fixed in this checkout** — both were silently weakening the evidence:

1. `parse_suite` dropped every *documented* test: unittest prints the name, the docstring, then the
   status on three lines, so the single-line regex captured 76 of 80 and set `complete: false`,
   which makes every attribution inconclusive. Normalised now: **80/80, `complete: true`**.
2. Captures were **not verbatim**: the child printed with the host locale (cp1252) while the parent
   decoded utf-8, so the `·` in the health line was stored as `�`. The child now runs with
   `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8` and the decode is utf-8, so the stored health text reads
   `banks 9 · categories 238 · bad digests 0 · missing modules none · newest edit 14:41` exactly.

v1's false positive (signature matching hit *passing* test names such as `test_duplicate_graph_id`)
is gone in v2: signatures are classified only from failure blocks.

**Evidence names its commit.** The gate records `git.sha` per capture and the report carries
`tested_commit` + `captured_clean`. Artifacts are committed in a commit whose parent **is** the
tested commit, so a reviewer can always resolve `tested_commit` to the tree that produced the
numbers. Capturing before committing the guards you just wrote is what makes a report name the
previous commit — correct, but worth stating rather than discovering.

**Capture before you patch.** The one thing that cannot be recovered afterwards is the baseline: a
report can only attribute by name if the pre-patch state was captured. Run
`host_gate.py --host … --capture before.json` *before* applying a patch, not after — every future
gate cycle starts there.

---

## Routing honesty (M15)

Reported symptom: *"chat is going straight to model first."* The ordering was already slash → task bus
→ fast path → AIML/daemon → model, so the cause was not order - it was two silent handoffs:

1. **A policy refusal fell through to the model.** A memory write without the grant returned no local
   answer, so the daemon's "deferred to the model" handed it on and the model improvised a reply
   instead of saying `memory writes need /allow memory`. A refusal is an answer: the daemon now closes
   the turn as `refused` with the reason, and the host renders it under *Local refusal (not
   authorized)*.
2. **The heading table had three keys.** `memory`, `memquery`, `refused` and `plan` turns would raise
   `KeyError` in the renderer; it is now a `.get(kind, "Local")` map covering every kind.

Handoffs that remain are real ones, and they now say so: before streaming, the chat mounts
`No local answer → delegating to the model (<phase reason>)`. A genuine no-match still reaches the
model - the goal is to know which turns are which, not to answer everything locally.

The guards drive the app end to end (type, press enter, assert a Response appears) rather than only
calling `local_answer`, because the crash lived in the renderer, not in the router.

---

## Identity and mark (M14)

Asked who it is, the host answers as itself and names what it can reach. The bank only routes
(`WHO ARE YOU`, `ARE YOU ALICE`, … -> `IDENTITY`); the host renders the name, the phase cycle, the
model list with tiers and the default marked, the advisors, and the mark - all read from the running
configuration, so the answer cannot drift from what is loaded.

```
I am a **Micronaut Daemon Bot** - a local, six-phase terminal agent. Not ALICE: the ALICE corpus is
vendored data I can learn patterns from, not who I am.
Phases: Pop → Wo → Yax → Sek → Ch'en → Xul ...
Serving: gpt-oss-20b via llama-server · no mode set
Models I can talk to (fastest → deepest, * marks the default): ...
My mark (the header animates this vector): <20x20 art>
```

`ARE YOU ALICE` deliberately resolves to the same introduction: the corpus is a knowledge source, not
an identity. The daemon admits `IDENTITY` as local text in Ch'en, so the routing stays uniform.

**The mark was too big.** Three things were downsized, because the box - not the file - is what fills
the header: `logo.png` 256x171 -> 128x85 (58 KB -> 16 KB), the `#welcome-logo` box 32x16 -> 22x11, and
`LogoArt`'s art grid 30x30 -> 20x20 (10 rows). The guard asserts the box size rather than the pixel
size, since shrinking the PNG alone would not have changed the header.

---

## AIML bundle → host (M13)

The review called this M12; in this checkout M12 is user memory, so the bundle guard is **M13**. It is
a narrow integration, not a second compiler: the host consumes the package's six-contract bundle and
its resolvers, and turns a node reference into a proposal.

```
aiml_host.validate()                 -> BINDINGS_VALIDATED over 6 contracts
aiml_host.propose("aiml://category/main#3")
    pattern WHO IS * · template 2 segments · srai 0 · capabilities none
    authorized False · persistence None
aiml_host.admit(proposal)            -> admitted True · executes False · persistence None
```

The four invariants, each with a guard:

1. **No independent compiler.** Resolution goes through `aiml_bundle.Bundle` and `resolvers.resolve`;
   the module never matches text. Matching stays in the python-aiml kernel where it belongs.
2. **No authority from declarations.** A proposal carries `authorized: False` and `persistence: None`
   whatever the document says, and `admit()` reports `executes: False`. A forged proposal claiming
   authority is refused (`forged_authority`), as is one from a bundle that is not validated
   (`stale_bundle`).
3. **No direct database writes.** Proposing and admitting are pure reads: the guard hashes
   `logs/memory/user.events.jsonl` and `task-list.json` either side and requires them unchanged.
4. **No bypass around the graph.** A foreign scheme (`gml://`), a foreign schema document, and an
   unresolved node id are all refusals (`BundleRefused`), never silent passes.

Capabilities declared in GML (`requires [ capability … ]`) are checked against a caller allowlist and
are otherwise refused (`capability_not_allowed`) - declaring a capability authorizes nothing. The two
functions are exposed through the typed registry as read-only, so the daemon and the model can consult
the bundle without gaining anything from it.

Deferred deliberately: no AIML bundle execution, no template rendering, no SRAI evaluation, no graph
mutation. The bundle is declarations; the host resolves and refuses.

---

## User memory (M12)

AIML stops being a pattern-to-string engine here: a pattern *proposes* a memory operation, the host
admits it, the JSONL event log records it, and the GML projection relates it.

```
MY DOGS NAME IS MAX        ->  MEMORY remember pet.name MAX     (proposal)
                                  Ch'en: memory writes need /allow memory   (refused -> deferred)
                                  after the grant: evt-000000 appended, chained
WHAT IS MY DOGS NAME       ->  MEMQUERY pet.name   (read-only, always admitted)
                                  "pet: name is MAX."          (from the projection)
```

Rules the tests hold it to:

- **Recognition is not authority.** `memory.aiml` alone writes nothing; the daemon routes the
  directive through `admit_memory`, and a refusal defers to the model like every other refusal.
- **History is append-only.** A correction appends (`Max` then `Rex`); the projection resolves the
  newest event; provenance survives. The log is hash-chained through `ledger_plugin`, so editing an
  event is detected exactly like a tampered ledger record.
- **Identity isolation.** Every read and write is scoped to one user id (`/user <id>` switches); the
  graph for one user never names another's facts.
- **Erasure beats history.** `MEMORY erase` compacts the log — the only destructive operation — and
  appends a tombstone recording that it happened; other users are untouched.
- **The projection is a view.** `graph()` builds a GML document and `validate()` checks it against
  `memory.gml` (ids unique, edges resolve, schema right). It is derived state, never a second
  authority; the JSONL log and PLAN.md remain canonical for history and ledger respectively.

What this is **not**: no ARPA grams, no embeddings or vector recall, no consent UI, no encryption at
rest, no cross-device sync, and `admit_memory` is a host check rather than a full XCFE engine. Those
remain separate milestones; the boundary between proposing and authorizing is the part that is real.

---

## Layer boundary

Three layers, kept distinct so that one is never mistaken for proof of another:

1. **GML documents and registries** - declarations, graph relationships, schemas (`ledger.gml`,
   `schemas/tensor-registry.gml`, the phase banks). Data; grants nothing.
2. **Trusted validation and admission** - the Python bootstrap, bindings, constraints and authority
   checks (`functions.py`, `planner.py`, `phases.py`, the sandbox). This is where authority lives.
3. **Host runtime and evidence ledger** - authorized operations, test evidence, audit records
   (`host_gate.py`, `tests_host/`, `ledger_plugin.py`, `backup.py`).

Self-hosting, AIML bundle integration and cryptographic-ledger construction are separate milestones:
none of them is implied by the guards above.

---

## Optional audit ledger (M10)

`ledger_plugin.py` is opt-in. It appends host events to an append-only JSONL file where each record
carries `sequence`, `previous_hash`, `content_hash`, `timestamp` and - when a key is available - an
Ed25519 signature over the canonical body. `host_gate.py --ledger <path>` records a gate verdict; the
default is off, and a recorded verdict authorizes nothing.

- **Canonical form** is `json.dumps(body, sort_keys=True, separators=(",", ":"))` over UTF-8, and
  floats are refused: byte-stable serialization is a guarantee, so a payload either has one or the
  append fails.
- **The digest covers content only** - `content_hash`, `signature` and `public_key` are excluded from
  their own body. That was a real bug on first write: the digest was computed before those fields
  were added, so every record failed its own verification until the exclusion was explicit.
- **Tamper evidence is per index**: editing, deleting or reordering a record breaks `content_mismatch`,
  `sequence_gap` or `broken_link` at a named line, and `append()` refuses to add to a chain that no
  longer verifies.
- **Signing is explicit**: a record is signed only when the caller passes a key or the
  `KNUMATIC_LEDGER_KEY` env var is set - the mere presence of `.ledger-key.pem` must not silently
  change what the ledger records. `ed25519:` signatures verify against the record's `public_key`, a
  wrong key fails, and an unsigned ledger reports `signed 0 / unsigned N` with `algorithm: sha256
  only` rather than implying authenticity it does not have.
- **What it is not**: a distributed ledger. One authority, no consensus, no network validation, no
  double-spend prevention. It is a tamper-evident audit trail for this host, which is what the
  evidence record needs.

`ledger.gml` describes the record shape and the plugin reads it, so the document stays the source of
truth for the shape while the host enforces it - and, as always, describes rather than authorizes.

---

## Last verified

```
kuhul-phase-engine-v0.1.0: python -m unittest discover -s tests   ->  Ran 80 tests, OK
                            occurrences of "schema mismatch": 0 (the F14 signature is gone)
base_health    : banks 9 · categories 238 · bad digests 0 · missing modules none
extension      : gml-tensor/1 owned by gml.tensor · fields 19 over data, graph, slice, tensor,
                 tensor.shape · constraints 6 · operator ASSEMBLE
discovery      : 4 tensor documents owned, 7 foreign skipped (no validation under the wrong contract)
malformed      : ExtensionError: document has no schema
cross-schema   : AssemblyError: reference schema mismatch: expected 'gml-tensor/1',
                 got ['aiml-gml/1'] for 'gml://categories/main'
repeatability  : data.value repeatable 1 · duplicate dtype -> tensor.dtype required once ·
                 four value entries in one data block -> valid
gml_validate   : col_a / assembled STRUCTURALLY_VALIDATED · category OUT_OF_SCOPE (aiml-gml/1)
gml_assemble   : tensor/assembled shape=(6, 2) dtype=float32 coverage=12/12 (plan only)
gml_audit      : admitted and run through the planner
package suite  : 80 tests, OK (rerun by M5 on every host-guard run)
host guards    : 9 tests, OK  (python -m unittest discover -s tests_host)
harness tests  : 14 tests, OK (python -m unittest test_host_gate, in the package)
host guards    : 54 tests, OK (M3-M15: guards, ledger 11, backup 5, memory 9, bundle 10, identity 6, routing 3)
evidence chain : artifact commit's parent == report `tested_commit` == 6b06884
```

Merge order used: **F14 → F14.1 → M2 → M2.1 → base suite → `base_health()` → `extension_summary()`
→ host tools**. F14/F14.1/M2/M2.1 are now **host-verified** in this checkout, which is the state the
ledger records — superseding the earlier "host-unverified" note in the standalone patch report.

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

**F15 — the three F14.1 distinctions, and only one of them is a skip.** Verified in this checkout:

| Situation | Behaviour | Evidence |
|---|---|---|
| foreign document during **discovery** | skipped, not validated under the wrong contract | `load_directory`: 4 owned, 7 skipped |
| foreign document **referenced** by a validated graph | rejection, because the binding is checked | `AssemblyError: reference schema mismatch: expected 'gml-tensor/1', got ['aiml-gml/1'] for 'gml://categories/main'` |
| document with **no schema** | malformed, rejected | `ExtensionError: document has no schema` |

`resolvers.resolve(ref, docs, expected_schema=…)` is the seam: `assemble.py` passes
`expected_schema="gml-tensor/1"` for whole-graph references, so a tensor caller and an AIML caller
each enforce their own boundary without the resolver knowing either schema.

**F16 — M2.1 repeatability and error scope.** `data.value` is declared `repeatable 1`; every other
field defaults to non-repeatable, so a duplicate `dtype` is `tensor.dtype required once` while four
`value` entries in one `data` block validate. Validation errors name the scope
(`unregistered field in data block: data.vaule`, `unregistered field: graph.coverag_policy`), which
is what makes a typo report point at the right level instead of a generic rejection.

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
:: 0. capture BEFORE patching anything, or the report cannot attribute by name afterwards
cd kuhul-phase-engine-v0.1.0
python host_gate.py --host . --capture ..\host-gate-before-v2.json

:: 1. the base's own suite must be green before anything is merged
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
- **M7 boundary:** `PLAN.md` is the canonical ledger; `task-list.json` is derived, regenerable state
  and never a second authority. The mirror can be deleted and rebuilt from PLAN.md alone, which is
  what the M7 test does.
- **Backups (M11):** an independent bundle now exists under `backups/` (gitignored), and its restore is
  verified by cloning it and running both suites from the clone. That closes "a force-push loses
  history": the bundle holds every ref, and its SHA-256 is in `manifest.json` and in the audit ledger.
  What it does **not** close is off-machine retention - the bundle lives on this disk until someone
  copies `backups/` elsewhere. Verified restore is not the same thing as an independent copy.
