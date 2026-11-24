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
host guards    : 155 tests, OK (M3-M24: guards, ledger 11, backup 5, memory 9, bundle 10, identity 6, routing 4, tools 8, gitops 10, clone 11, server 10, greeting 11, corpus 14, knowledge 9, links 12, gml2 15)
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
