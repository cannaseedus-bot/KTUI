# Security notes: what is required, what is optional

This is a **local application** for one person on one machine. It is not a service with hostile clients, and the
threat model is written down here so the word "security" stops meaning three different things at once.

## The threat model, plainly

- **In scope:** a component handing malformed data to another component; a model or retrieved document being
  mistaken for an authorized instruction; evidence about a test run being wrong or irreproducible; secrets ending up
  in a transcript or a log because the application put them there.
- **Out of scope:** a hostile operator of this machine (it is the user's own computer), a network attacker (the HTTP
  server binds `127.0.0.1` only), multi-user tenancy, and claims of independently validated accuracy (there is no
  independent reviewer, and the tooling cannot create one).

"Other people shouldn't have access in the first place" is a legitimate starting point. Most of what follows exists
because **one component should not be able to corrupt another**, not because someone is expected to attack the box.

## Three different concerns, not one

| Concern | Mechanism | Required? |
|---|---|---|
| **Correctness** — a component must not accept invalid data | typed schema checks (`schema_bus`), operator graph validation (`plan_graph`), proposal validation (`proposal`) | **yes** — needed even with no adversary |
| **Controlled execution** — reading is not authorization | `authority: "declaration_only"`, `admitted: false`, capability gates, `phase_routing` refuse/fallback | **yes** — this is the one boundary that must never be relaxed |
| **Evidence about evidence** — is a recorded result reproducible and attributable | SHA-256 digests, hash-chained ledger, same-commit gate, Ed25519 attestations, reviewer onboarding | **optional facility** — for claims of evaluation, not for the runtime |

The third row is where the James-Bond feeling came from. It answers "can I defend this evaluation as independently
validated?", which is a scientific question, not a defensive one.

## What the runtime actually depends on

Nothing in the runtime path imports the cryptographic layer, and a guard (`tests_host/test_runtime_independence.py`)
enforces it:

```
runtime:  chat_app · phase_routing · binding_resolver · schema_bus · learning_pipeline
          runtime_tree · model_lifecycle · inference_session · profile · grams · corpus · model_router
optional: review_attestations · keymaker · evidence_gate · evaluation_harness · rescore · review_packet
```

Delete the optional column and K'UHUL still reasons, retrieves, composes and answers. Keep it, and you additionally
get reproducible evaluation with signed attestations - an **evaluation facility**, not a gate every interaction
passes through.

## The boundary that stays

```
[Pop model.output]
  [Wo content] → "proposal"
  [Ch'en validate] → "schema"
  [Ch'en authority] → "not_admitted"
  [Xul execution] → false
[Xul]
```

**Data does not become an instruction by being read.** An AIML pattern, a GML fact, a REST payload or a model reply
is content. Acting on it requires an explicit, capability-gated step. This is the whole reason proposals are not
admissions, and it protects against accidents as much as against anyone deliberate.

## Secrets: where they can actually leak

A local model has no persistent memory and cannot open files. Three real paths remain, and they are all in the
application, not the model:

1. **The application puts a secret in the prompt** (a tool that dumps a config file into the context).
2. **The application gives the model a tool** that can read or run things; the model can request, and the host
   decides. That decision is the permission boundary, not the model's goodwill.
3. **The application records the interaction.** Transcripts and the evidence ledger keep what they are given -
   prompt text is stored as a SHA-256 digest plus a length, but a tool's output is not automatically digested.

What is deliberately not built: a bot that hands a user their API token on request. A bearer secret that a model can
echo turns the transcript and the ledger into a disclosure channel, and hash-chained leaks are still leaks.

## Optional facilities, kept and not expanded

- `review_attestations` / `keymaker` exist and are tested; the registry holds only the author, and the corpus
  reports **0 independently approved**. No further cryptographic infrastructure is planned.
- `evidence_gate` requires three suites at one commit; it is cheap and it caught a real regression.
- Anything that would need TLS, OAuth, session stores or a remote identity service is **out of scope for this
  application**. A profile file per user (`profile.py`) is configuration, and it refuses capability and secret keys
  by design.

## If this ever becomes a network service

The following would need a real design review before this code went beyond `127.0.0.1`: identity and authentication,
per-user authorization rather than per-machine capability sets, TLS, secret storage and rotation, and rate limiting.
None of it is needed for a workstation, and none of it is pretended here.
