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
| M16 | Tool calls run for real; the fast path refuses instead of fabricating | **guard** | `chat_app.py` (`safe_math`, `fast_path_outcome`, utf-8 subprocess decode), `tests_host/test_tools.py::M16…` |
| M17 | Commit, push and build on command, with git's own output or error; model tools stay read-only | **guard** | `gitops.py`, `gitops.aiml`, `chat_app.py` (`admit_gitop`), `tests_host/test_gitops.py::M17…` |
| M18 | Clone a repo: https only, contained in the workspace, behind the write grant | **guard** | `gitops.py` (`clone`, `validate_remote`, `validate_destination`), `chat_app.py` (`clone_repo`), `tests_host/test_clone.py::M18…` |
| M19 | Reachable endpoint: `micronaut://v1/chat` over loopback, local answers only | **guard** | `micronaut_server.py`, `chat_app.py` (`/serve`, `--serve`), `start.bat serve`, `tests_host/test_server.py::M19…` |
| M20 | Greeting-µ: `greeting.gml` declares greetings, destinations and the paths between them; multi-intent messages keep every clause | **guard** | `greeting.gml`, `greetings.py`, `chat_app.py` (`multi_intent_answer`), `tests_host/test_greetings.py::M20…` |
| M21 | The loaded AIML corpus ports to one GML document, verified against the sources | **guard** | `aiml_to_gml.py`, `aiml-corpus.gml`, `tests_host/test_aiml_corpus.py::M21…` |
| M22 | The daemon knows facts locally (curated ALICE banks) and offers depth instead of spending a model call | **guard** | `knowledge.py`, `chat_app.py` (`_maybe_offer`, `pending_deep`), `tests_host/test_knowledge.py::M22…` |
| M23 | Answers carry clickable reference links (Wikipedia, Britannica, NASA, Space.com) labelled as searches | **guard** | `links.py`, `chat_app.py` (`maybe_reference`, `/links`), `micronaut_server.py`, `tests_host/test_links.py::M23…` |
| M24 | The five GML/2 contract issues: reference modes, dynamic SRAI, runtime cycle guard, capability ladder, ordered templates | **guard** | `srai_resolver.py`, `aiml_host.states`, `core/rules.py` (segments required), `tests_host/test_gml2_contracts.py::M24…` |
| M25 | AIML round-trip conformance: 131 real categories migrated, validated, and answering identically to python-aiml | **guard** | `aiml_graph.py`, `tests_host/test_aiml_roundtrip.py::M25…` |
| M26 | Retrieval and composition: the two contracts are consumed - rank relations, compose a verified paragraph | **guard** | `compose.py`, `compose.aiml`, `aiml_contracts/{retrieval,composition}.gml`, `tests_host/test_compose.py::M26…` |
| M27 | EmbeddingGemma2 vector adapter verified against the real 99,524-row assets; similarity ranks, compatibility filters, XCFE admits | **guard** | `adapters/embeddinggemma2.py`, `tests/test_vector_adapter.py` (14 tests) |
| M28 | K'UHUL program layer: the declared grammar parses, validates, serializes and traces (no execution) | **guard** | `core/program.py`, `tests/test_program.py` (15 tests) |
| M29 | `kuhul-phases/v1` manifests: one JSON file per phase, chained by schema URI, regulated by a loader that executes nothing | **guard** | `core/phase_manifest.py`, `phases/json/*.json`, `tests/test_phase_manifest.py` (16 tests) |
| M30 | `phase.resolve_aiml`: one input, one typed six-phase plan - evidence, delegation, no execution | **guard** | `phase_resolve.py`, `tests_host/test_phase_resolve.py` (15 tests) |
| M31 | The 58 declared phase operations classified: registered / requires-grant / proposal-only / unbound | **guard** | `kuhul-phase-engine-v0.1.0/phase_ops.py`, `tests/test_phase_ops.py` (10 tests) |
| M32 | The bridge: walk the manifests with a carried context, dedupe a duplicated binding, visit every phase | **guard** | `phase_chain.py`, `tests_host/test_phase_chain.py` (13 tests) |
| M33 | The five operators with rank discipline, and URI resolution that navigates without granting | **guard** | `operators.py`, `tests_host/test_operators.py` (14 tests) |
| M34 | Daemon consumes the phase chain as the first routing boundary, with an explicit fallback policy | **guard** | `phase_routing.py`, `chat_app.py` (`phase_route`, `granted_capabilities`), `tests_host/test_phase_routing.py` |
| M35 | Grant-aware routing: an absent grant blocks, a present grant permits only its own scope, a match grants nothing | **guard** | `phase_routing.route`, `tests_host/test_phase_routing.py::M35…` (12 tests total) |
| M36 | Operation proposals: a six-field prediction the host validates, converts and still does not admit | **guard** | `proposal.py`, `tests_host/test_proposal.py` (14 tests) |
| M37 | `kuhul-rest/v1`: a declarative route manifest and a read-only adapter with four guards | **guard** | `rest_adapter.py`, `data/rest-routes.json`, `micronaut_server.py`, `tests_host/test_rest.py` (15 tests) |
| M38 | Per-request identity and scope: the transport authenticates, an engine-wide grant cannot widen a caller | **guard** | `rest_adapter.py` (`identity_for_token`, `_authorize`), `data/identities.json`, `tests_host/test_rest.py::M38…` (22 tests total) |
| M39 | Decision closure under unknown probabilities: UNKNOWN is never 0.5, and an action collapses without a fact collapsing | **guard** | `decision.py`, `tests_host/test_decision.py` (15 tests) |
| M40 | Micronaut registry: typed agents and typed edges, with structural / routing / authority reported separately | **guard** | `micronaut_registry.py`, `data/micronauts.json`, `data/micronaut-edges.json`, `tests_host/test_micronaut_registry.py` (16 tests) |
| M41 | Shared corpus resolver: authorized retrieval, typed evidence, per-agent projection; retrieval ≠ learning ≠ training | **guard** | `corpus.py`, `data/corpus.json`, `tests_host/test_corpus.py` (15 tests) |
| M42 | Model router: registered endpoints only, AIML answers first, a binding is not an invocation | **guard** | `model_router.py`, `data/models.json`, `tests_host/test_model_router.py` (17 tests) |
| M42.1 | Two live backends (advisor 9032, worker 9040), `--port` on the launcher, explicit preference outranks the declared default | **guard** | `model_router.select`, `task-engine.py --port`, `data/models.json` |
| M43 | Inference evidence records and the three-path comparison: what the corpus saves, with unmeasured values left None | **guard** | `evidence_record.py`, `tests_host/test_evidence_record.py` (14 tests) |
| M44 | Proposal evaluation: can the 1B model produce valid K'UHUL plans? Scored by the existing validators | **guard** | `proposal_eval.py`, `runtime_servers.py`, `data/proposal-eval-live.json`, `tests_host/test_proposal_eval.py` (10 tests) |
| M45 | Live evidence capture: one request id per turn, digest not prompt, execution distinguished from admission, recording can never break an answer | **guard** | `chat_app.record_turn`, `evidence_record.build`, `/evidence`, `tests_host/test_live_capture.py` (9 tests) |
| M46 | Composition as a graph: the host resolves edges, never repairs, and scores nodes/edges/authority separately | **guard** | `plan_graph.py`, `proposal_eval.py`, `data/proposal-eval-fair.json`, `tests_host/test_plan_graph.py` (17 tests) |
| M47 | A third backend: Qwen3-1.7B planner (thinking off) fixes over-generation and is the cheapest of the three, but under-generates the full chain | **guard** | `data/models.json`, `task-engine.py --no-think`, `data/proposal-eval-qwen.json`, `tests_host/test_model_router.py` (20 tests) |
| M48 | Inference on demand: a registered wake, owned stops, leases that keep a shared backend up | **guard** | `model_lifecycle.py`, `data/models.json`, `tests_host/test_model_lifecycle.py` (15 tests) |
| M49 | The frozen evaluation corpus: reviewed expectations, nodes scored apart from edges, headline restricted to frozen cases | **guard** | `evaluation/`, `evaluation_harness.py`, `tests_host/test_evaluation_harness.py` (13 tests) |
| M50 | `runtime://green-screen/v1`: one read-only tree over the registries, bound to the UI, answering 'why this model' | **guard** | `runtime_tree.py`, `chat_app /runtime`, `tests_host/test_runtime_tree.py` (13 tests) |

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

## The runtime projection (M50)

One read-only tree over what already existed, so the phase hive and the UI read the same field:

```
runtime://green-screen/v1 · 28 node(s) · 51 edge(s)
  corpus 5 · evidence 1 · micronaut 5 · model 3 · phase 6 · preference 4 · runtime 1 · schema 3
  model://advisor        hot   port 9032
  model://planner        hot   port 9041
  model://worker         hot   port 9040
  evidence://ledger      records 35 · chain ok
  (read-only projection · the registries and XCFE are authoritative)
```

Nodes come from the phase manifests, the micronaut registry, the model declarations and lifecycle, the
corpus declaration and the evidence ledger - not from a copy. Edges are typed: `has_phase`, `precedes`,
`hands_off_to`, `accepts`, `binds_to`, `prefers`, `has_corpus`, `has_model`, `records_binding`.

**The questions the review listed are now answerable from the tree:**

```
why did the router pick planner for compose?
  explain_selection -> selected: planner · health {advisor: true, planner: true, worker: true}
                       order: [planner, advisor, worker] · rejected: []
who binds to the advisor?
  users_of(advisor) -> []      (nothing declares it: it is the escalation target, listed in
                                preference://plan as rank 1)
```

That last one is the honest answer rather than a convenient one: after M47 the advisor is the *fallback*,
not a declared binding, and the tree shows the difference instead of inventing a user.

`/runtime` in the app renders the same projection into the command panel, so the green screen is the
Textual surface over this field - the registries stay authoritative, and the projection carries
`execution: false`, `mutation: false` on every node.

---

## The frozen evaluation corpus (M49)

The grader is now a corpus artifact rather than a test file, with the review's fields and its review gate:

```
evaluation/
  manifest.json         12 cases · 8 frozen · 2 reviewed · 2 draft · frozen_ids + isolation rule
  cases.jsonl           id, category, input, expect{phase, graph{nodes,edges}, targets, refusal, unknown_facts}
  expected-graphs.gml   the same facts in GML: node per case, edge per plan step, nested accumulate
  results/              written by the harness, one file per model and run
```

**Only `frozen` cases count toward the headline**, and the manifest's `frozen_ids` must match the file - a
guard tampers with it and requires the load to fail. `isolation()` proves nothing in the live path reads the
corpus, because an evaluation that can retrieve its own expected answers stops measuring generalization.

Scoring keeps the failures apart, which is the point:

| a reply | scored as |
|---|---|
| `map, filter` for a `filter -> map` case | **nodes** ✓, **edges** ✗, `wrong_order`, not complete |
| `filter, map, reduce` for a pair case | `extra_operators`, not complete |
| a plan for "commit and push" | **not a refusal**: the case needs the refusal, so it fails |
| truncated JSON | `parsed: 0` and `truncation` counted separately |

A perfect model scores 8/8 complete with 3/3 refusals - the corpus's own self-check, run in the tests.

### What is still missing before the headline number

The corpus is **8 frozen cases across 6 categories**, authored and reviewed by me, not independently. That
is enough to exercise the scoring and to catch the two failures already measured (Gemma over-generating,
Qwen under-generating), but it is not yet the 50-100 case set the review specified. The honest next step is
adding cases - especially SRAI redirects and REST reasoning, which have no frozen case yet - and having them
reviewed rather than written by the same process that grades them.

---

## Inference on demand (M48)

The router chose among *healthy* endpoints; it could not wake a stopped one. Now it can, and only through a
registered launch:

```
model lifecycle · 3 model(s) · declaration_only
  advisor  declared cold  now hot   port 9032 · idle 300s
  planner  declared cold  now hot   port 9041 · idle 600s
  worker   declared hot   now hot   port 9040 · idle 900s
  (only a registered launch can wake a model; only an owned, unleased process sleeps)
```

Four rules, each guarded:

| rule | how it holds |
|---|---|
| only a registered launcher runs | the manifest names alias, port and flags; a `launch.command` field is **refused at load** - a proposal cannot contribute a command |
| only an owned process is stopped | ownership is the pid this lifecycle started on the declared port; a backend somebody else launched is left alone (tested) |
| never stop while leased | `acquire()`/`release()` count users; with a lease live, `release_idle()` keeps the backend and says `leased` |
| never stop before the timer | a release restarts the idle clock; a sweep inside the timeout reports `not_idle` |

**WARM is declared unsupported rather than faked.** `llama-server` in this build loads the model at start,
so a backend is either listening (HOT) or not (COLD); the state report says so instead of inventing an
intermediate state. `wake` on an already-hot port returns `started: false` and launches nothing.

The intended steady state on this machine: **Gemma hot** (conversation), **Qwen cold until a plan is
needed**, **GPT-OSS cold until the advisor is escalated to** - which is what the declarations now say, with
idle timeouts of 900 s, 600 s and 300 s respectively.

---

## Three backends, three roles (M47)

```
advisor  gpt-oss-20b   :9032  chat, tools        complex reasoning
worker   gemma-3-1b    :9040  chat, code         conversation
planner  qwen3-1.7b    :9041  chat, code, json   structured planning (thinking off)

relations -> planner · compose -> planner · aiml -> worker · eliza -> worker
```

Qwen needed a per-launch flag, so `task-engine.py launch --no-think` appends `--reasoning-budget 0` without
changing what the advisor receives. Verified: the probe replied `OK` in 5 tokens with no
`reasoning_content`, so thinking really is disabled rather than assumed.

### The same two tasks, the same 900-token budget, the same validator

| task | gemma-3-1B | qwen3-1.7B (no think) | gpt-oss-20B |
|---|---|---|---|
| `filter -> map` | `filter,map,reduce,filter` - **extra_operators** | `filter,map` - **exact** | `filter,map` - **exact** |
| full chain | `filter,map,accumulate,reduce` - **misplaced_accumulate** | `accumulate,reduce` - **misplaced_accumulate, missing 2** | `filter,map,accumulate,reduce` - **misplaced_accumulate** |
| completion tokens | 245 | **106 / 107** | 815 |
| latency | 15.3 s | **8.3 / 11.1 s** | 163 s |

Qwen fixes the failure that Gemma had - it does not over-generate the two-step instruction - and it is the
cheapest and fastest of the three. But it fails the full chain in the **opposite** direction: it emits two
of the four operators, dropping `filter` and `map` entirely, and it still uses `accumulate` where the graph
requires `fold`.

So the small-model problem is not "one model is better": Gemma over-generates, Qwen under-generates, and
both misuse `accumulate`. The instruction says "accumulate evidence", and all three models read that as a
step. The graph contract is correct; the prompt is the weak link.

---

## Composition as a graph (M46)

The model may now name operators without edges, and the host resolves them - while **never repairing a
wrong plan**:

```
{"phase": "Sek", "operators": ["filter", "map", "fold", "reduce"], "authority": "proposal"}
```

`plan_graph.compare()` reports four facts separately, because a plan can have the right operators and the
wrong connections:

| proposal | verdict | why |
|---|---|---|
| `filter, map, fold, reduce` | `exact` | |
| `filter, map, fold, accumulate, reduce` | `exact` | nested `accumulate` is the same graph |
| `filter, map, accumulate, reduce` | `misplaced_accumulate` | `accumulate` used where `fold` belongs - not a substitute |
| `filter, map, reduce, filter` | `extra_operators` | two extras, `fold` missing; the proposal is preserved, not trimmed |
| `filter, map` | `missing_operators` | short plans stay short |
| `map, filter, fold, reduce` | `wrong_order` | same nodes, different edges |
| any of the above with `authority: "execute"` | `authority_ok: false` | scored separately from the plan |

### The fair-budget result changed the conclusion

The first comparison truncated the 20B at 400 tokens, so the advisor "failed" on a harness limit. At 900
tokens and a 420-second client timeout, both models answered the full-chain task:

| | worker gemma-3-1B | advisor gpt-oss-20b |
|---|---|---|
| operators | `filter, map, accumulate, reduce` | `filter, map, accumulate, reduce` |
| verdict | `misplaced_accumulate` | `misplaced_accumulate` |
| completion tokens | 245 | 815 |
| latency | **15.3 s** | 163.2 s (10.6x) |

**Both models produced the same plan, and both made the same contract error** - using `accumulate` as a
standalone step where the graph requires it nested inside `fold`. So on this task the 20B bought 10.6x the
latency and 3.3x the tokens for an identical result.

That points away from model capability and toward **the instruction**: the prompt says "accumulate
evidence", and both models reasonably emit `accumulate`. The next experiment is a prompt that states the
fold/accumulate relationship explicitly, run against the same validators - which is a cheaper and more
informative test than escalation.

`score_plan()` now records `tokens: {total, reasoning, final_json}` and keeps each component `None` when
the server does not report it (`final_json` needs both, so it is `null` here), plus `finish_reason` so a
truncation is never mistaken for a wrong answer.

---

## Live evidence capture (M45)

The recorder is now fed by real turns. Each turn gets one request id, and the record joins the phase
chain's verdict, the binding, the latency and the execution semantics:

```
last turn `a349e23d4039` · inference local · 172 ms · executed True · admitted False
evidence log · 6 record(s) · chain verified · C:\Users\canna\.aiml\logs\inference\records.jsonl
```

`/evidence` (or Ctrl+P) shows that. Three properties, each guarded:

- **the prompt is digested, not stored** - `input_sha256` and `input_chars` identify a turn for
  reconstruction without keeping what the user typed;
- **recording is best effort** - a test patches the log writer to raise `OSError("disk full")`, and the
  answer still renders while `last_record_error` names the failure. An observation that breaks a turn
  would be a worse defect than a missing observation;
- **observed execution and proposal admission are separate fields** - `admission.proposal_admitted` stays
  false while `observed_execution` is true for a turn where a tool actually ran (`git status`), so the log
  cannot truthfully say "nothing was admitted" while omitting that the host performed an authorized read.

The `/evidence` command is registered in the palette and reports the chain state, so a tampered log is
visible from the UI rather than only in a test.

---

## Can the 1B model plan? (M44)

Measured, at smoke scale, with the validators that already existed - not with a fluency judgement.

```
                         worker (gemma-3-1B)        advisor (gpt-oss-20b)
parsed                    2/2                        1/2  (one truncated)
valid proposals           8                          2
operator order            1/2                        1/1
authority violations      0                          0
completion tokens         492                        734
mean latency              12.9 s                     90.7 s
```

What the plans looked like:

- worker, `full_chain`: `filter, map, accumulate, reduce` - the operators are all valid and `accumulate`
  is a legitimate answer to "accumulate evidence", but the `next` fields did not chain
  (`chain_mismatch`);
- worker, `filter_map`: `filter, map, reduce, filter` - over-generated for a two-step instruction;
- advisor, `filter_map`: `filter, map` - exactly right;
- advisor, `full_chain`: **truncated** at the 400-token budget (20B spends tokens before its JSON).

So on this sample the small model is **~7× faster and parses more often**, while the large model is more
precise when it finishes. That is a real signal and *not* a benchmark: two tasks, one run, one prompt
shape. The honest next step is a held-out task set with several runs, which the harness already supports
(`evaluate(models, runs=N)`).

Two defects the harness itself found, both mine rather than the models':

1. **`stop: ["\n\n"]` truncated formatted JSON** - a stop sequence is wrong for an output that is
   multi-line by nature. Removed; the budget is 400 tokens and `finish_reason` is now recorded.
2. **Truncation was being reported as `unparseable`**, which blames the model for the harness's limit.
   The two outcomes are now distinct, and the report says which happened.

Operational fix from the same review: `runtime_servers.py` stops the process **listening on one port**
(`127.0.0.1:9040` → its PID) instead of `taskkill /im llama-server.exe`, which would have taken the
advisor down with the worker.

---

## Inference evidence (M43)

The measurement the review asked for, with the honesty constraint built in: **unmeasured is `None`, not
zero**.

```
aiml_only      corpus=1  model=0  route_ok=1     (1 of 4 turns resolved without a model)
aiml_worker    corpus=1  model=3  route_ok=4     (3 turns need a backend; worker selected)
aiml_advisor   corpus=1  model=3  route_ok=4     (the same 3 turns, advisor selected)
eliminated: 1 of 4
```

A record carries every field the review listed - closure, action, micronaut, binding, reported model id,
retrieval counts, operators, schema validation, admission, tokens, latency - and two properties are
enforced rather than described:

- **measurements are measurements**: `tokens: None` when nobody counted (a test forbids 0), `latency_ms`
  is integer milliseconds because the log is chained through the ledger, whose canonical form refuses
  floats;
- **records observe, they never admit**: every record says `admitted: false`,
  `authority: "declaration_only"`.

The log is hash-chained like the audit ledger, so a record cannot be quietly edited - a guard tampers with
one and requires the chain to break.

`compare()` runs the same task list through `aiml_only`, `aiml_worker` and `aiml_advisor`, measuring what
each path *did*: turns the corpus handled, model invocations, route validity, and wall-clock latency. It
reports `answer_quality: None` and `tokens: None` because it performs no inference - judging answers needs
live completions and a grader, and a fabricated number would poison the measurement it exists to support.

One accounting bug the guards caught: `corpus_handled` was computed as "no binding", which made the
corpus-only path look like it handled every turn. It is now a property of the turn (the chain resolved or
refused it), so `aiml_only` correctly reports 1 of 4.

---

## Two live backends (M42.1)

The router's `worker` slot is now served, not hypothetical:

```
python task-engine.py launch --model gemma-3-1b --port 9040 --keep-alive

  advisor  ok 200  46 ms  gpt-oss-20b-MXFP4.gguf        (port 9032)
  worker   ok 200   0 ms  gemma-3-1B-it-QAT-Q4_0.gguf   (port 9040, 1.2 GB)
```

`task-engine.py` gained `--port` (it read the port only from the config), and `select()` now lets an
**explicit** preference outrank a micronaut's declared default - without that, "switch this turn to the
fast model" could never override `relations -> advisor`:

```
aiml      (no preference) -> worker      declared default
compose   (no preference) -> advisor     declared default
relations (preference=fast) -> worker    override
compose   (preference=fast) -> worker    override
aiml      (preference=deep) -> advisor   override
```

And the worker answers for real: a `chat/completions` call to 9040 replied `"Yes."` with
`gemma-3-1B-it-QAT-Q4_0.gguf` as the model - the binding is not decorative.

The worker's features are `["chat", "code"]`, matching how the model is used here; `worker` costs 1.2 GB
against the advisor's 0.9 GB resident (both were already loaded in this checkout).

---

## Model router (M42)

The LLM becomes an interchangeable backend, and the corpus decides whether one is needed at all.

```
model router · 2 model(s) · 5 route(s) · declaration_only
  advisor  complex_reasoning  http://127.0.0.1:9032/v1  ['chat', 'tools']
  worker   fast_inference     http://127.0.0.1:9040/v1  ['chat']
  micronaut://v1/aiml -> worker · eliza -> worker · memory -> worker
  micronaut://v1/relations -> advisor · compose -> advisor
  (declaration_only · a binding is not an invocation)
```

The probe ran against the live server in this checkout: **advisor healthy in 62 ms**, listing
`gpt-oss-20b-MXFp4.gguf`; **worker unreachable** (nothing on 9040), reported with its latency rather
than treated as absent.

Two rules, each guarded:

- **Only registered endpoints are probed.** An unregistered name is refused with `model_not_registered`
  and *no URL is contacted* - a test asserts the result carries no `url` key. The manifest refuses a
  non-loopback base URL and refuses `require_registered: false`, so "a port that answered" can never
  become a model.
- **AIML answers first.** `plan_invocation()` asks the phase chain: when the chain handles the turn the
  result is `invoke_model: false, "no tokens spent"`; when the chain *refuses* it, a model cannot
  override the refusal; only an unhandled turn proposes a backend.

Selection is deterministic and reports why alternatives were rejected: the micronaut's declared model
first, then the preference order (`fast` / `deep`), filtered by probe success and required features
(`worker` declares only `chat`, so a `tools` request lands on `advisor`). An unrouted micronaut is refused
with `micronaut_not_routed` rather than silently given a default backend.

---

## Shared corpus resolver (M41)

One knowledge graph, many specialised views - and the three operations kept apart:

```
corpus corpus://shared/v1 · 5 source(s) · 5 operator(s) · declaration_only
  aiml://categories            patterns    shared  available
  gml://relations              relations   shared  available
  gramstore://ngrams           ngrams      shared  UNAVAILABLE
  memory://jsonl               events      self    available
  vectors://embeddinggemma2    embeddings  shared  available
  read: scope_checked · write: xcfe_admitted
  training: separate process; a corpus update never retrains a model
```

**Retrieval** returns typed evidence with provenance (`kind`, `ref`, `source`, and the event id for
relations), never writes, and is refused rather than degraded:

| case | refusal |
|---|---|
| a source the declaration marks unavailable | `source_unavailable` - *"no GramStore exists in this checkout"*, stated up front |
| a source not in the declaration | `source_not_declared` |
| a caller without the source's capability | `capability_not_granted` |
| a `self`-scoped source with no identity | `scope_required` |

**Incremental learning is a proposal**, not a write: `propose_update()` returns
`requires: "xcfe_admitted"`, `persisted: false`, and the note that *a corpus update never retrains a
model*. The manifest is validated to refuse `write: "allowed"` and to require that `model_training`
states it is a separate process - so the three operations cannot be quietly merged by editing the
declaration.

**Training is not here at all**, and the boundary is declared data rather than a comment.

`view()` gives the micronaut-specific projection: with the capability and an identity, four sources are
readable and one is unavailable; without the capability, nothing is readable; without an identity,
`memory://jsonl` is `scope_required`. Same corpus, different lenses - which is the whole claim.

---

## Micronaut registry (M40)

The registry the review asked for: one typed lookup over what was scattered, plus the **typed edges** that
make a hand-off a declaration rather than an assumption.

```
micronaut registry · 5 agent(s) · 6 declared edge(s) · 4 schema(s)
  micronaut://v1/aiml       pattern_recognition    utterance/v1  -> candidates/v1
  micronaut://v1/relations  graph_reasoning        candidates/v1 -> proposition/v1
  micronaut://v1/memory     user_memory            candidates/v1 -> proposition/v1
  micronaut://v1/eliza      conversational_fields  proposition/v1 -> utterance/v1
  micronaut://v1/compose    composition            proposition/v1 -> answer/v1
  (declaration_only · a declared edge is not an admission)
```

**Three guarantees, reported separately because each can fail alone:**

| guarantee | when it holds | when it does not |
|---|---|---|
| structural | the payload's schema is produced by a registered agent | `schema_not_declared` |
| routing | a declared edge accepts that schema (from the declared source) | `no_declared_edge` |
| authority | the **caller** holds the edge's capability | `capability_not_granted`, with the denied edges listed |

And `admitted` is **always false** - the fourth term of `SchemaCompatible ∧ EdgeDeclared ∧
CapabilityAuthorized ∧ XCFEAdmitted` belongs to XCFE, not to this module.

Consequences the guards pin down: a payload naming `{"$schema": ..., "target": "gml://users/42"}` routes
nowhere (the target is inert; only declared edges count); `answer/v1` is structurally valid but unroutable
because no edge consumes it; `proposition/v1` from `relations` is **ambiguous** (eliza or compose) and the
first by `(source, target)` is selected with the rest listed; and an edge whose schemas disagree with its
endpoints is refused at **load**, so the registry cannot describe a hand-off it could not perform.

---

## Decision closure (M39)

The review's numbering calls this M34; here it is M39 because M34/M35 were the routing guards. The two
invariants are enforced, not documented:

| invariant | how it is held |
|---|---|
| `UNKNOWN(P(b)) != 0.5` | a missing probability stays `None`; `expected_utility()` returns `None` for any action with one, and the `expected_utility` policy **refuses** with `probabilities_unknown` instead of substituting a prior or falling back to another policy |
| `Xul(Action) !=> Xul(Fact)` | `close_action()` sets `action_collapsed: true` and `fact_collapsed: false`; `close_fact()` requires its own `PASS`/`FAIL` verdict, and a test proves `"UNKNOWN"` is refused |

The review's table, exactly:

```
query : +8 (unknown), -2 (unknown)     worst case -2
skip  :  0 (deterministic)             worst case  0

policy=minimax         -> selected: skip · worst_case {query: -2, skip: 0} · action_collapsed True
policy=expected_utility-> refused: probabilities_unknown · selected None · action_collapsed False
```

Policies are typed rather than blended: `expected_utility` needs every probability of every action (and
they must sum to 1), `minimax`/`maximin` need only utilities - which is precisely why it can decide while
the probabilities stay unresolved. Ties are broken **by name** and reported, so a choice is reproducible
rather than insertion-order dependent.

A decision is a proposal: `authority: "proposal"`, `execution: false`, `mutation: false`. `action_collapsed:
true` means a choice was selected - not that anything ran.

---

## Per-request identity (M38)

The confused-deputy gap the review named, closed. Identity now comes from the **transport**, not from
the request's text:

```
GET /api/users/42   Authorization: Bearer token-42   -> 200  {"id": "42", "name": "Bill", "status": "active"}
GET /api/users/42   (no header)                      -> 403  no authenticated identity
GET /api/users/42?as=42  Bearer token-42             -> 400  identity may not be asserted in the query
GET /api/users/7    Bearer token-42                  -> 403  caller '42' may not read '7'
GET /api/users/42   Bearer token-42-forged           -> 403  no authenticated identity
```

Three properties hold, each with a guard:

- **a forged identity cannot override** - `?as=` is refused outright (400), and there is no `caller=`
  argument left in the adapter to fall back on;
- **an engine-wide grant cannot widen a caller** - `granted` is the host's own capability set, and
  `_authorize` checks the *identity's* capabilities first: if the engine holds the capability and the
  caller does not, the answer is 403 with "engine-wide, not granted to …". Identity 7 carries
  `users.read.any` in its own scope and may read 42; caller 42 cannot read 7 even when the engine is
  granted `users.read.any`;
- **a denial leaks nothing** - 403/404/400 responses carry `status`, `error`, `route`, `method` and the
  three effect flags only: no `body`, no `allowed`, no `returned`, no `withheld`, no field names, no
  trace of whether the record exists.

The fixture registry stores **sha256 of each token**, not the token, and says in the file that it is a
test fixture rather than an authentication system. That is the remaining honest limit: loopback, fixture
identities, no TLS - the boundary is now explicit rather than assumed.

---

## REST adapter (M37)

`kuhul-rest/v1` is a route manifest; `rest_adapter.py` connects the three components that already
existed - HTTP in `micronaut_server`, manifests in `phase_manifest`, operators in `operators` - and
serves a **projection of authorized data**, not a generated answer.

```
GET /api/users/42?as=42  ->  200  {"id": "42", "name": "Bill", "status": "active"}
GET /api/users/42x       ->  400  malformed parameter 'id' (expected integer)
GET /api/users/99  as 42 ->  403  caller '42' may not read '99'
GET /api/unknown         ->  404  unknown route
GET /api/users/42        ->  403  caller '' may not read '42'
```

The four guards are enforced, each with a status and a reason:

| guard | behaviour |
|---|---|
| route confinement | only declared method+path; `{id}` is a **typed** parameter (`integer`), so `42x` is 400 not a lookup |
| read authorization | the route's capability must be granted (manifest name or the host alias `graph.relations.read`); a caller may read only their own resource unless `users.read.any` |
| projection confinement | `user.public.v1` allows `id, name, status`; `email` is recorded, **withheld**, and reported as withheld; a fact never recorded stays missing rather than invented |
| effect confinement | the manifest refuses `execution/mutation/persistence` that are not `false`, and every response reports all three false |

A manifest that declares `mutation: true` fails to load - a guard proves it. The operator pipeline runs
over the facts (`filter -> map -> fold -> reduce`) and is reported with the response.

---

## Operation proposals (M36)

The smaller prediction problem, made checkable. A model does not generate a program; it names six fields:

```json
{"phase": "Sek", "operator": "filter", "target": "graph.matches",
 "binding": "valid", "next": "map", "authority": "proposal"}
```

`proposal.validate` checks the vocabulary and the shape - unknown phase, unknown operator, a target whose
reference is not registered (`http://…` refused, `gml://…`/`⟁DATA` accepted), a `filter`/`map` without a
binding, a `next` that is neither phase nor operator, and any authority claim other than
`proposal`/`declaration_only`. `validate_all` also follows the chain (`next: map` must actually be
followed by a map) and treats an operator in an unusual phase as a **notice**, not a refusal - the
architecture is explicit that a phase may use an operator for its own purposes.

Accepted proposals convert to declarative source and are validated **again** by the program layer:

```
Sek {
  filter("graph.matches", "valid")
  map("graph.matches", "transform")
  fold("evidence")
  reduce("evidence")
}
```

And a valid proposal is still **not admitted**: `admitted: false`, `execution: false`,
`authority: declaration_only`. That is the point - the model proposes, the host establishes validity, and
XCFE decides what may run.

Bugs found while wiring: `next` was required to be a *phase*, while the review's table uses the next
*operator* (`Next: MAP`); and targets emitted as bare identifiers failed the program layer's strict
identifier checks, so they are emitted as strings.

---

## Daemon consumes the chain (M34 / M35)

The review's two guards, implemented. The numbering differs from the review's because M32/M33 are the
chain bridge and the operators; the substance is what matters.

**M34 - consumption.** `local_answer` now consults `phase_routing.route()` before anything else, keeps
the verdict (`last_routing`) and the plan (`last_plan`), and the fallback policy is explicit:

```
who is bill            action=chain    closure=delegated   -> the answer path runs (host has no QUERY verb)
tell me about my dog   action=chain    closure=delegated   -> compose answers
hello                  action=fallback closure=none        -> the banks answer
git status             action=fallback closure=none        -> the tool path answers
```

`delegated` means a directive matched - **not** that its operation was admitted. The chain is consulted,
the plan is preserved, and the existing answer path still does the answering.

**M35 - grants.** A route that requires an execution-class capability refuses when the grant is absent,
and - the rule the review insisted on - **there is no fallback in that case**, because falling back
would run the same operation through the unrestricted path the grant exists to gate:

```
COMMIT THE TREE -> GITOP commit, capability repo.write
  no grant            -> refuse  ("requires repo.write; no fallback runs an operation ...")
  /allow git          -> chain   ("the required grant is present for this exact scope")
  /allow memory only  -> refuse  (a different grant does not cover the route)
  WHO IS * -> QUERY   -> fallback when graph.relations.read is withheld (read-class falls back)
  WHO IS * with no capability -> chain (a plain binding asks for nothing)
```

Capability class is decided by name (`*write*`, `*commit*`, `*persist*`, `*execute*` are execution;
everything else is read), and `granted_capabilities()` names what this session holds
(`graph.relations.read` always; `memory.write` only after `/allow memory`; `repo.write` only after
`/allow git`; `file.write` only after `/allow`).

`/chain <text>` shows the verdict for any input, including the reason it fell back or refused.

---

## Operators and URI chains (M33)

The phases say *when and under what authority*; the operators say *what happens to the data*. Both are
implemented, and both refuse to decide authority.

**Operators, with the rank discipline the architecture turns on:**

| operator | rank | guarantee |
|---|---|---|
| FILTER | preserved | same shape, fewer items; pure (the input list is untouched) |
| MAP | preserved | one in, one out *by construction* - a transform cannot change the collection size |
| FOLD | preserved | the accumulator's rank survives; ACCUMULATE is its state update |
| REDUCE | collapsed | collapses along a declared axis (`max` / `min` / `sum`), and says so in provenance |

```
pipeline(4 candidates) -> FILTER 4->1 -> MAP 1->1 -> FOLD 1->1 -> REDUCE 1->1
  selected: {axis: score, selected: {ref: aiml://vector/1, score: 1.0}, rank: 0}
  authority: declaration_only · execution: false
```

Each stage's provenance records `count_before`, `count_after` and `rank`, so a claim about a fold
preserving rank (or a reduce changing it) is checkable rather than asserted.

**URI resolution navigates; it does not grant.** Five schemes resolve to typed data -
`kuhul://phases/pop` reads the manifest, `aiml://category/what-is#1` names a node,
`gml://enterprise/relations` a graph, `micronaut://v1/chat` the daemon endpoint,
`srai://route/what-is` a route. Every envelope carries `authority: declaration_only` and
`execution: false`, and the resolver refuses unregistered schemes (`http://`, `file://`), a missing
manifest with a reason rather than a traceback, cycles, and depth or budget overruns. A walk stops at the
first refusal and reports both sides.

One dead check removed while writing the guards: `apply_map` compared lengths *after* a list
comprehension, which can never differ - the invariant is structural, so the test now asserts the
property instead of expecting an error that could not happen.

---

## The phase chain bridge (M32)

The two declaration layers now meet in one read-only resolver: the AIML banks supply recognition, the
JSON manifests supply identity, order, bindings and capabilities, and the plan carries context from
Pop to Xul.

```
python phase_chain.py "who is bill"
phase chain · 'who is bill' · 6 phase(s)
  chain: Pop -> Wo -> Yax -> Sek -> Ch'en -> Xul
  Pop    WHO IS * -> WHAT IS bill
  Wo     no match
  Yax    WHAT IS * -> QUERY bill
  Sek    no match
  Ch'en  no match
  Xul    (no bindings)
  closure: delegated - a directive was matched; the host owns the execution
  capabilities required: graph.relations.read
  (execution false · authority declaration_only)
```

The review's two details, as behaviour:

1. **The duplicated redirect.** `python phase_chain.py "who is bill" --original` re-tests every phase
   against the original input, and the duplicate becomes visible instead of merely present:
   `duplicate: WHO IS * applied in Pop, declared again in Wo`, with Wo's copy *shadowed* and never
   re-run. In the default mode the input advances with the redirect, so the second copy cannot fire at
   all - both facts are asserted.
2. **A visit is not a match.** All six phases appear in every plan. A phase with nothing to match is
   recorded as `no_match` with the context intact, so the chain is operationally connected rather than
   silently skipping.

Capabilities are collected only where declared (`graph.relations.read` on Yax and Sek, nothing on Xul),
and the closure is always a proposal: `delegated` for a directive, `redirected` for an SRAI, `none`
when nothing matched. Nothing executes.

Bug found while writing the guards: directive targets did not substitute captures, so
`QUERY {star:1}` reached the closure unrendered instead of `QUERY bill`.

---

## Phase operations audit (M31)

The six phase banks declare **58 operations** in their headers (112 categories: 21/14/16/23/20/18).
That is vocabulary and intent - so the audit answers the only question that matters for integration:
for each operation, what actually exists?

```
python phase_ops.py            # (from kuhul-phase-engine-v0.1.0)
phase operations · 6 bank(s) · 112 categor(ies) · 58 operation(s)
  registered      34
  requires_grant   7  execute_tool_chain, dispatch_call, compare_and_commit, gramWrite,
                      persist_state, update_authorized_metric_parameters,
                      invalidate_dependent_projections
  proposal_only    8
  unbound          9
  (declaration_only · a match grants nothing)
```

- **registered (34)** name a real capability that is imported and checked callable -
  `find_best_pattern_match -> aiml_graph.match`, `srai_xcfe_propose` resolves through
  `srai_resolver`, `verify_*` through `aiml_host.validate`/`states`, `compose`/`aggregate` through
  `compose.py`, `manifest_lookup` through `phase_manifest.load`.
- **requires_grant (7)** is exactly the set the review singled out: Sek's `execute_tool_chain` and
  `dispatch_call`, Xul's `compare_and_commit`, `gramWrite`, `persist_state`,
  `update_authorized_metric_parameters`, `invalidate_dependent_projections`. They are gated, never
  registered - and a guard enforces that: tamper the table and `violations()` names the operation.
- **proposal_only (8)** is what the host can do without granting anything: propose a fold, rank
  candidates, route - not emit an answer, since emitting is the host's.
- **unbound (9)** says why: no encoder for `embedgemma_prompt_vectorize`, no sense inventory, no BFS
  over the projection (`graph_bfs` - the projection exists, the traversal does not), no n-gram
  confidence, no MathML reader.

So the answer to "which are implemented, which are proposal-only, which have validated host bindings"
is data, regenerable, and checked: a wrong binding fails the suite (`verify_eliza_candidate_provenance`
pointed at a nonexistent `phase_resolve.verify` until the audit caught it), and a gated name can never
be classified `registered`.

---

## phase.resolve_aiml (M30)

The integration point the review named, and nothing larger: one AIML input in, one **typed phase plan**
out, read-only.

```
why does my dog act playful?
  Pop    one candidate: WHY DOES * DOG *        (captures: my dog, playful)
  Wo     subject=dog · attributes=[playful] · question_type=explanation · reflected "your dog"
  Yax    0 redirects · 0 vectors · 3 recorded facts
  Sek    filter / map / fold proposals over 3 candidates
  Ch'en  3 evidence · problems: subject_not_recorded, unsupported_explanation
  Xul    partial: "pet is described as playful, big, but there is no recorded cause for that behaviour."
```

Four closures, and the distinction is the point of the whole thing:

| closure | when | response |
|---|---|---|
| `supported` | attributes recorded, question answerable | the answer |
| `partial` | attributes recorded, **cause is not** | "described as …, but there is no recorded cause" |
| `unknown` | nothing recorded | "Nothing recorded supports an answer yet" |
| `delegated` | directive or identity (TOOL/IDENTITY/COMPOSE/…) | empty - the host owns it |
| `none` | a statement, not a question | empty |

Other properties: the plan is **deterministic** (no timestamps; identical JSON on repeat), **typed**
(six phases in fixed order), and **read-only** (`execution false`, `authority declaration_only`, and
`admitted: false` in Ch'en). Vector candidates are accepted from a retriever and stay in Yax - a guard
asserts they never become evidence.

Bugs the guards caught: the ELIZA reflection applied both directions, so `my -> your -> my` undid
itself; `_sek` pre-filtered facts by a *guessed* subject and silently dropped everything when the guess
was wrong (now Ch'en decides the subject and reports `subject_not_recorded`); and greetings/directives
were being closed from memory until the delegation gate moved ahead of the statement gate.

---

## Phase manifests (M29)

A phase does not need a `.khl` program or a `.aiml` file to be useful. `phases/json/pop.json` …
`xul.json` are `kuhul-phases/v1` manifests that carry pure AIML paths, AIML bindings, and a `next` URI:

```
python core/phase_manifest.py phases/json
kuhul-phases/v1 chain: Pop -> Wo -> Yax -> Sek -> Ch'en -> Xul
                       (6 manifest(s), 6 aiml file(s), 5 binding(s))
```

The format is regulated, and the regulation is the interesting part:

| check | behaviour |
|---|---|
| schema id | must be `kuhul-phases/v1` |
| phase | one of the six; `Chen` and `Ch'en` both accepted, canonicalized |
| uri | if declared, must agree with the phase (`uri_mismatch` otherwise) |
| `aiml` | a missing file is *reported*, never assumed to exist |
| `bindings` | need a target; `{star:N}` may not exceed the pattern's wildcard count |
| `next` | resolved by schema URI inside the manifest set; unknown schemes are errors |
| chain | cycles, repeated phases and over-long chains are bounded failures that print the chain |

Chaining is by URI (`kuhul://phases/wo`, `phases://`, or a bare `<name>.json`), so the order is data:
edit one `next` and the chain changes, which is the property the six-phase cycle was supposed to have.

The loader loads nothing into a kernel: `authority: declaration_only`, no `aiml` import, no subprocess.
A guard asserts that, so a future "convenience" that starts executing from a manifest fails the suite.

---

## K'UHUL program layer (M28)

The grammar in `grammar/kuhul-grammar.ebnf` is now implemented rather than documented:

```
glyph DATA = "enterprise:records"   relation RISK = "risk_shipping"
lane risk : Graph { map(⟁DATA) filter(⟁DATA) bind ⟁DATA -> risk }
Pop { … } Wo { … } Yax { … } Sek { … } Chen { … } Xul { … }
```

- **parse** covers every construct in the grammar: declarations, the eight opcodes, phase blocks, lane
  blocks with the eight types, bindings and `⟁glyph` references. `Chen` and the corpus's `Ch'en` both
  parse and canonicalize to `Ch'en`.
- **validate** covers what parsing cannot: opcode vocabulary, argument arity per opcode, lane types,
  unresolved glyphs and unknown references. **Phases are a vocabulary, not a schedule**: any subset in
  any order is valid - `Wo { … }` alone, or `Xul` before `Pop` - because a phase is meaningful only for
  the work it does. The report records `phases`, `canonical` and `order`, and only an unknown phase
  *name* is an error. `strict_order=True` is available for callers that want the sequence enforced.
- **serialize** is round-trip stable (`parse(serialize(parse(x)))` equals `serialize(parse(x))`).
- **trace, never execute**: `evaluate()` walks in phase order and records each step with its resolved
  arguments and declared effect; an unbound opcode is `deferred` with the reason, a raising one records
  its error, and the trace carries `execution: false · mutation: false · authority: host`.
- the **bracket dialect** ships too: `graphs/shipping-impact.khl` parses into the same AST, so the
  example the package already contained is now readable as a program instead of opaque text.

Two bugs found by the guards: `validate` unioned a lane *dict* with a set (a `TypeError` the tests
caught immediately), and the bracket reader treated the phase word as the opcode, so
`[Yax resolve "…"]` produced zero instructions - the shipped example validated as an empty program
until the reader was rewritten to group by phase.

---

## EmbeddingGemma2 vectors (M27)

The adapter existed as a scaffold that had never seen the real assets - its own README said the JSONL
structure had not been inspected. It has now been run against all five files:

```
rows 99,524 · dimensions 256 · float32 · three 100 MB .npy lanes · 52 MB bindings (1.7 s to parse)
record: {"index": n, "A": {"vector_row": n}, "B": {"vector_row": n}, "pattern": …, "template": …,
         "authority": "data_only"}
validate() -> VALIDATED_READ_ONLY, coverage == vector count
```

The first real defect: `pairs()` required a flat `vector_row` per record, which the producer never
writes, so `validate()` failed on line 1 of the bindings. The row is the record's `index`, and
`A.vector_row`/`B.vector_row` must agree with it - a record contradicting itself is a contract error,
not a silent guess.

**Ranking is not authorization**, and the adapter now enforces that rather than documenting it:

| surface | does | never does |
|---|---|---|
| `retrieve(vector)` | chunked cosine on one lane | admit, execute, persist |
| `retrieve_by_row(row)` | nearest neighbours of an existing row | embed text |
| `lookup(text)` | exact pattern lookup | pretend an unseen phrase has a vector |
| `for_text(text)` | exact hit, then neighbours; else `NO_ENCODER_MATCH` | fabricate an embedding |
| `compatible(pattern, text)` | AIML wildcard compatibility | score anything |
| `rank_and_filter(text)` | keeps compatible, reports dropped | let a high score bypass structure |

Measured on the real data: `rank_and_filter("what is ai")` keeps row 1 (`WHAT IS AI`, 1.0) and drops
88,107 / 88,466 / 93,242 (`WHAT IS A AI`, `WHAT IS AN AI`, `WHAT IS AN ARTIFICIAL INTELLIGENCE`) -
semantically close, structurally unable to bind. Every candidate stays `PENDING_XCFE`.

There is no text encoder in this repository, and the adapter says so instead of substituting one: an
unseen phrase returns `NO_ENCODER_MATCH`. Vector assets are `data_only`; they rank candidates and
grant nothing.

---

## Retrieval and composition (M26)

The gap named at the end of M25 is closed: `retrieval.gml` and `composition.gml` were contracts nothing
read. Both are now load-bearing, and the paragraph is verified before anyone sees it.

```
you : my dog's name is Rex  ·  my dog is playful  ·  my dog is big
you : tell me about my dog
bot : pet (Rex) is playful and big. That is everything I have recorded about pet (Rex).
      (3 relation(s), verification passed)
```

- **retrieval.gml** declares `strategy lexical_then_recency`, the two weights, `min_score 0.10` and
  `max_candidates 6`. Scoring is `0.7 * lexical-overlap + 0.3 * recency`, filtered by the threshold,
  capped by the contract, and sorted deterministically.
- **composition.gml** declares the output type, `max_sentences`, `attribute_order`, the separator, the
  conjunction and the sentence templates. Editing `max_sentences 2 -> 1` in a copy changes the answer,
  which is asserted.
- **verification before prose**: an attribute that is not in the projection fails with
  `unsupported_attribute` and the paragraph is withheld - "nothing was invented to fill the gap" is
  the wording the user gets. A value that changed (Max -> Rex) is a **warning**, not a failure: the
  projection already answers with the newest, so history is reported without blocking.
- the name is treated as an identifier, not an attribute: "pet (Rex) is playful and big" reads;
  "pet is Rex, playful and big" does not.

One real defect surfaced while making the guards hermetic: `user_memory` bound `path=EVENTS` as a
default argument, so the module captured the file at *import* time and monkeypatching `EVENTS` had no
effect - tests were reading the production log. Every entry point now resolves the path at call time.
That is why the "empty memory" guard could pass while the real log had facts in it.

Also fixed while wiring: `compose.aiml` had been overwritten with an unrelated 112 KB Python file (a
corrupted write), and the `local_answer` branch for `compose` had landed *after* the `gitop` return,
unreachable. Both are now correct and guarded.

---

## AIML round trip (M25)

The step the review named as the gate before migrating a corpus: `AIML → GML → validated graph →
matching → SRAI → rendered output`, compared with the interpreter.

```
131 categories from five host banks  ->  0 unsupported
migrated set assembled as the six contracts  ->  Bundle.validate() = BINDINGS_VALIDATED
17 inputs  ->  17/17 replies identical to python-aiml
```

The four roles are kept distinct, as specified: `category` is a relationship object carrying
`pattern_ref`/`template_ref` and its provenance (`bank:index`); `pattern` holds the expression and
wildcard count; `template` holds ordered `segment [ ordinal ... ]` entries; `srai` is an expression node
with `max_depth 3` and `visited_guard 1`, not an edge to a fixed category.

What the comparison found, and what it cost to fix: python-aiml captures with the **user's case**, so
"my dogs name is Rex" must render `MEMORY remember pet.name Rex`. Matching is case-insensitive, but
captures are built from the original tokens - the graph was uppercasing them, and the round-trip test
is what exposed it. 17/17 is the result after that fix, not before.

Bounds are proven, not assumed: two categories redirecting to each other terminate with
`SRAI loop at ...`, and a six-hop chain stops at `max_depth 3 exceeded`. A directive such as
`TOOL git status` comes back as **text** - the graph renders it and never executes it.

Unsupported constructs are reported, never approximated: a `<that>`-context category appears in
`problems` as `unsupported` and is excluded from `migrated`, so the migration count and the corpus
count cannot silently disagree.

Scope: patterns made of literals and `*` are migrated; `<that>`, topics and nested template constructs
are not, and the module says so rather than pretending. Migrating the remaining corpus is now a
mechanical extension of this harness, and the corpus projection (M21) already lists which banks exist.

---

## GML/2 contract issues (M24)

The review's five points, checked against the real package rather than the draft. Three already held,
two did not, and one hole was found in the package itself.

| issue | state | evidence |
|---|---|---|
| 1. references | **already held** | `resolve()` rejects `pattern:1` as an invalid reference, distinguishes `gml://` (whole graph) from `aiml://` (node-addressable) by mode, and refuses a foreign schema; `endpoint_modes_consistent` rejects mixed endpoints |
| 2. dynamic SRAI | **already held** | `srai_static_ok` refuses `@redirects_to` on an expression containing `{star:N}`; `srai_guards_present` requires positive `max_depth` and `visited_guard 1` |
| 3. cycle guard | **was missing** | the package only checked that guards were *declared*; `srai_resolver.py` now enforces `max_depth` and a visited set keyed on the **resolved expression plus its captures**, so a loop that only appears after substitution is caught |
| 4. capability states | **was missing** | `aiml_host.states()` implements the ladder and stops a portable graph at `STRUCTURALLY_VALIDATED` when this host lacks a capability, naming it - rather than calling a good graph `REJECTED` because a plugin is absent |
| 5. ordered templates | **hole found** | segments were supported but a template with *no* segments passed the ordinal rule vacuously, so the `spans`/`slots` form was silently accepted; `template_ordinals_contiguous` now requires ordered segments |

Parser/serializer property, also asserted: `serialize(parse(x))` is stable under a second round trip
for all six contracts.

The one base-package change is `core/rules.py` (segments required). It is a tightening, the package's
own 80 tests stay green, and the F14/M2 guards are unaffected - but it is a change to the base, so it
is recorded here rather than folded into a host commit quietly.

Not claimed: `EXECUTABLE_CANDIDATE` and `ADMITTED` are never reported by the validator. It says where a
document set stopped and why; admission remains the host's decision.

---

## Reference links (M23)

A factual answer now ends with places to read more - clickable, and honest about what they are:

```
Reference links · searches, not pages I read
- [Wikipedia (search)](https://en.wikipedia.org/w/index.php?search=saturn)
- [Britannica (search)](https://www.britannica.com/search?query=saturn)
- [NASA (search)](https://www.nasa.gov/?s=saturn)
- [Space.com (search)](https://www.space.com/search?searchTerm=saturn)
```

Two rules shape it. **No guessed article paths**: a search URL resolves for any spelling of the
topic, while `/wiki/Saturn's_ring_composition` is a guess that may 404. **No claim of having read
them**: the label says searches, because the local answer came from the AIML corpus and the model's
came from training - neither browsed, and this sandbox has no outbound network to browse with.

Space topics get NASA and Space.com on top of Wikipedia and Britannica; everything else gets the first
two. Topics are extracted from the question ("what is Saturn" -> `saturn`) with social phrases and
sentence-length strings rejected, so a greeting never gets a Wikipedia search stapled to it.

Three surfaces carry the links: a local knowledge answer, a model answer that has none of its own
(`maybe_reference`, which leaves an answer that already cites something alone), and `POST /v1/chat`,
which returns them as a `links` array for clients to render. `/links <topic>` prints them on demand.

---

## Knowing things, and offering depth (M22)

Reported: *"What is Saturn? (Alice knows what Saturn is!) (but sent question to model?)"* - correct
diagnosis. The ALICE knowledge was on disk but never learned: the tarball has no `startup.xml`, so the
host only ever learned `knumatic_learned.aiml`. Saturn sat in `knowledge.aiml` the whole time.

**Knowledge is learned now.** `knowledge.py` names a curated set - 21 banks, ~8,400 categories, about
0.4 seconds - learned **before** the host's own banks so python-aiml's later-learn precedence keeps
`hello`, identity, memory and git untouched:

```
what is saturn                -> Sixth planet from the sun, famed for its rings.
who is shakespeare            -> A 15th Century English playright, Shakespeare wrote "Romeo and Juliet".
what is the capital of france -> Paris.
hello                         -> the daemon's own greeting (the corpus does not shadow it)
explain quantum chromodynamics -> (nothing) -> the model, with a note
```

Eight banks are **excluded on purpose**, and the reason is measured rather than assumed: `default`,
`ai`, `alice` and `badanswer` carry catch-all patterns, while `that`, `update1`, `stories` and
`salutations` answer sentences they have no business answering - "hey, how are you, and can you check
my server?" came back as *"All of them?"* from `that.aiml` and *"I think there might be a few
exceptions."* from `update1.aiml`. Both broke the honest handoff and the multi-intent split.
`KNUMATIC_KNOWLEDGE=off` disables the set for a session.

**Depth is offered, not spent.** A short factual answer ends with *"Would you like me to delve deeper
into it?"*, and the host remembers the original question. Saying **yes** sends **that question** to the
model - not the word "yes" - and anything else cancels the offer:

```
you : what is saturn
bot : Sixth planet from the sun, famed for its rings.
      Would you like me to delve deeper into it? Say yes and I will ask the model about your
      original question.
you : yes
bot : [asks the model about "what is saturn"]
```

Greetings, identity answers, tool results, memory turns and refusals never offer depth, because there
is nothing to deepen. The guards capture the model call instead of making it, so the test asserts the
*question* the model would receive.

---

## The corpus as one document (M21)

```
python aiml_to_gml.py --write            -> aiml-corpus.gml   (39 banks · 8,787 categories · 1.92 MB
                                             4 registries · 9 core modules · 17 documents)
python aiml_to_gml.py --check            -> ok · 9,427 edges · 406 redirects resolved / 159 unresolved
python aiml_to_gml.py --write X --system -> + overlays/examples/legacy/grammar: 20 registries · 45 documents
python aiml_to_gml.py --write X --all    -> the vendored ALICE tree: 84 banks · 99,941 categories · 21.9 MB
```

The document now covers the whole runtime surface the review named, not only the banks:

- **banks** - every `.aiml` the host loads: its own, the package's `phases/`, `routing/xcfe.aiml` and
  `routing/kuhul-phases.aiml`, and every bank in `integrations/`;
- **registries** - `schemas/aiml-registry.gml` (schema id, owner, resolvers, all six constraint names),
  `registry.gml`, `tensor-registry.gml`, and the JSON phase contract, each with its digest;
- **core modules** - the nine files in `core/` with digest, line count, public names and first
  docstring line: the Python that validates all of this, described but never executed here;
- **documents** - the GML the registries validate: the six `aiml_contracts` and the tensor `contracts`,
  each with its schema, graph id, node and edge counts; a `validated_by` edge points at the registry
  whose `schema_id` matches, and those 16 edges are derived, not asserted.

`--system` adds the declarations the host does **not** load - overlays, examples, legacy documents,
grammar files, the JSON registry and schema folders - so "everything in the package" is reachable
without pretending it is loaded.

One node per bank (with its sha256 and byte count), one node per `<category>` (phrase, wildcard count,
template, kind, directive), one edge per containment, one edge per resolved `<srai>`, and an explicit
`srai_missing` node for a redirect that has no target in the projection. Nothing is dropped: `--check`
re-derives the inventory from the `.aiml` files and compares counts, digests, wildcard counts and the
complete redirect accounting (`resolved + missing == every <srai> in the sources`).

**Scope is stated, because "the corpus" is ambiguous.** The default is the 18 banks the host and the
daemon actually load. `--all` adds the vendored ALICE foundation set - 99,941 categories in a 21.9 MB
document that takes about 70 seconds, and whose check does **not** pass: `phone.aiml` reports a bank
count mismatch (its categories are declared without templates, which the projection skips) and 11,479
of 31,670 `<srai>` targets are absent from that set. That is the honest result, so the giant document
is measured and not committed.

What the document is and is not: it is a projection for inspection and verification - the redirect
structure of the corpus in one place, checkable against the files. It is not executable, the kernel
still loads the `.aiml` files, and the document carries a `no_grant_from_corpus` constraint saying so.

---

## Greeting-µ (M20)

A greeting is an entry point, not an answer. `greeting.gml` is the declaration: **14 nodes, 21 edges**,
one schema (`gml-conversation/1`), the greetings themselves, the social questions that ride along,
seven destinations, and the paths between them - all under a `no_grant_from_greeting` constraint.

```
HELLO/HI/HEY/YO/GOOD MORNING   -> conversation
HEY                            -> question, tool, command, memory, task, identity   (may_lead_to)
HOW ARE YOU / WHATS UP         -> conversation, tool
destination                    -> declared authority: read_only | proposal_only | requires_grant
```

`greetings.py` applies the document; it never executes or authorizes:

```
"Hey, how are you, and can you check my server?"
  -> greeting/conversation/read_only
  -> social/conversation/read_only
  -> destination/tool/proposal_only      authorized: False
```

Two rules that keep the message whole:

- **a greeting may open a longer clause** - "hey remember my dog's name is max" is a greeting *and* a
  memory proposal, not a greeting that swallows the rest;
- **connectors are not intents** - "and", "then", "also" are stripped, and the most specific cue wins
  ("who are you" is identity, not a generic "who" question).

The host then answers every clause locally, or hands the *whole* utterance on: a clause it cannot
answer means no partial answer (`multi_intent_answer` returns None). Single-intent messages take the
old path unchanged, which the guards assert so nothing regresses.

`greeting.gml` is load-bearing, and a test proves it by adding a greeting to a copy of the document
and requiring the new phrase to be recognised - there is no Python list of greetings to keep in sync.

Not yet wired, stated plainly: the graph routes, but the *destinations* still resolve through the AIML
banks and the daemon's admission boundary rather than through `ROUTE` as a first-class operator. The
candidate list is available for that integration; what exists today is the declaration, the
decomposition, and the all-or-nothing host behaviour.

---

## Reachable endpoint (M19)

The daemon answers on a port. The scheme is logical - nothing resolves `micronaut://` - so the honest
address is both:

```
micronaut://v1/chat   ==   http://127.0.0.1:8756/v1/chat

POST /v1/chat   {"message": "who are you"}   -> {"kind": "aiml", "reply": "...", "phases": [...]}
GET  /v1/health                               -> {"ok": true, "model": "...", "phases": [...]}
GET  /v1/models                               -> {"models": [...], "default": "..."}
GET  /v1/phases                               -> the six-phase trace of the last turn
GET  /v1/identity                             -> the daemon's self-description
```

Start it with `/serve [port]` in the TUI, `python chat_app.py --serve 8756`, `python
micronaut_server.py --port 8756`, or `start.bat serve [port]` (the bat's other modes leave the port
closed). It binds **127.0.0.1 only**; binding elsewhere prints a warning rather than pretending it is
safe.

**A network client can only read.** The endpoint answers from the local pipeline - AIML banks, the
six-phase daemon, memory reads, identity, git reads - and it never:

- calls the model: an unanswerable message returns `{"kind": "deferred", "reply": null, "note": "no
  local answer - the model is not invoked over the network"}`;
- writes memory: `my dogs name is max` comes back `refused` with `/allow memory`, and the event count
  is asserted unchanged;
- commits, pushes, clones or writes files: `commit this` returns `refused` with `/allow git`, and
  `/v1/health` reports `writes: false`.

Protocol errors are real too: an empty or malformed body is `400`, an unknown path `404`, a
non-GET/POST method `405`, and a body over 64 KB is `413`. Requests are serialised by one lock around
the pipeline so two clients cannot interleave the daemon's `last_turn`.

---

## Cloning (M18)

Cloning writes a directory tree into the workspace from the network, so it is the most constrained
operation here. Three surfaces reach the same code and the same grant:

```
/clone <https url> [directory]        host command      needs `/allow`
clone_repo(url, path, depth)          model tool        offered only when `/allow` is on
GITOP clone                           AIML intent       asks for the url, then same path
```

**Refused before any network call:**

- a scheme that is not `https` (`ssh://`, `git@host:…`, `file://`, `ext::…`);
- a url that starts with `-` or carries `--upload-pack`, `;`, `&&`, `|`, backticks or `$(`, so a flag
  or a command cannot be smuggled in as a remote;
- a destination that escapes the workspace (`../`, an absolute path) or is a non-empty directory;
- and `git clone` itself stays out of the sandbox's git allowlist, so `run_command` cannot reach it.

The grant is the file-write one, not the repo-write one: cloning creates files rather than rewriting
the current repository. Without it the message says exactly that and nothing is touched.

**One AIML limitation, stated rather than worked around:** an AIML kernel splits input on sentence
punctuation, so `https://github.com/x/y.git` arrives as `HTTPS` + fragments and a `CLONE *` pattern
would capture nonsense. The bank therefore only recognises the intent (`clone a repo`) and the host
asks for the url; the url goes through `/clone` or the model's `clone_repo`.

---

## Repository operations (M17)

The bot can build, commit and push on command - and shows what git said.

```
/build                  compile every tracked .py, then run the package suite   (read-only)
/commit [message]       git add -A, then git commit                            (needs /allow git)
/push                   push the current branch, authenticated first           (needs /allow git)
/sync [message]         commit then push; stops at the first failure           (needs /allow git)
/allow git [off]        the grant itself
```

The same phrasing works in natural language through `gitops.aiml`: *build it*, *commit this*,
*commit this as <message>*, *push it*, *commit and push*, *sync the repo*. A pattern only proposes -
the daemon routes `GITOP` through Ch'en, so a refused write is answered locally with `/allow git` and
nothing is touched.

**Honesty rules this module keeps:**

- an operation returns what git printed, with its exit code - `**ok**` or `**failed** (exit 128)` -
  and never claims success it did not have;
- a clean tree reports *nothing to commit - the working tree is clean* instead of inventing a commit;
- the default message, when none is given, is `checkpoint: N file(s) changed`, derived from the
  working tree rather than guessed;
- pushing tries the authenticated form first (the `gh` token, never printed) and falls back to plain
  `git push`, reporting the **last** error when both fail;
- **the model cannot do any of this**: the sandbox's git allowlist stays read-only, and a guard
  asserts that `add`, `commit` and `push` are unreachable through `git_command`.

One environment limit found while testing: pushing to a *local bare remote* makes git spawn `sh.exe`,
which this file sandbox refuses (`CreateFileMapping`, Win32 error 5). The orchestration (auth attempt,
fallback, error selection) is therefore unit-tested with an injected runner, while the failure path is
integration-tested against real git.

---

## Tool calls and the fast path (M16)

Reported: *"make sure the Daemon Bot tool calls are still working"*, with a screenshot of
`search the web for news on Nvidia` answering `🌐 Result for news on nvidia`. That was not a tool call
- it was a fabricated result for a tool this build does not have.

- **The fast path no longer invents anything.** A web request produces
  `No web tool in this build, so I cannot search for "…". The model can answer from its training data
  (which may be out of date) - it cannot browse either.` and then hands the turn to the model. A
  request that looks like arithmetic is *computed*: `safe_math` parses with `ast` and allows only
  numbers, `+ - * / // % **` and parentheses - no `eval`, no names, no calls, division by zero and
  runaway exponents refused. Anything else defers with a note instead of pretending.
- **A real bug surfaced while checking the tool calls:** `what is the diff` answered
  `'NoneType' object has no attribute 'strip'`. `Sandbox.run_command` decoded subprocess output with
  the platform default (cp1252), so any diff containing an em-dash or a box-drawing character failed
  to decode, left `stdout` as `None`, and was swallowed into a string. It now decodes utf-8 with
  `errors="replace"`, and treats a `None` stream as empty.
- **The verbs are asserted, not assumed:** `git status|diff|log|branch`, `time`, `convert`, `files`
  answer with real output; `rm` and `git push` are still refused by the sandbox.

The guard deliberately asserts the *shape* of tool output rather than searching for error words: a
`git diff` contains the source of the test, including the very strings a naive check would flag.

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
`No local answer → delegating to the model (<phase reason>)`, with "the AIML banks had no reply for
that" when no proposal existed at all. A genuine no-match still reaches the model - the goal is to
know which turns are which, not to answer everything locally.

**Small talk is a bank, not a model call.** `smalltalk.aiml` answers greetings, thanks, goodbyes and
"How can you help" locally; capability questions route to the identity answer. A greeting therefore
costs no round trip and prints no routing notice.

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
harness tests  : 14 tests, OK (python -m unittest test_host_gate, in the package)
host guards    : 424 tests, OK (M3-M50) · package suite 139 tests (14 vector-adapter, 16 program, 16 phase-manifest, 10 phase-ops)
evidence chain : artifact commit's parent == report `tested_commit` (see the latest 'Evidence for' commit)
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
