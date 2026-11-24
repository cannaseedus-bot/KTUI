# The Micro Agent bridge: what exists, what is missing

Inspected before adding anything, as the review asked. Every claim below is a file and a line you can check.

## Answering the three questions

| question | answer | evidence |
|---|---|---|
| Does the Micro Agent expose its AIML/SRAI routes to the Micronaut registry? | **No. The connection is missing.** | `srai_resolver.resolve()` returns `{reply, trace, depth}` - a rendered string. It has no concept of a handler URI, a capability, or a model alias. |
| Does `mu.py` accept SRAI-resolved capability requests and return typed results? | **No, and it is not that kind of module.** | `mu.py` opens *"KNUMATIC completion micronaut: six-phase, suggestion-only KUHUL pipeline. No execution... Candidates are declarations, not callable permissions."* It produces candidates for KNUMATIC, not responses for a KTUI turn. |
| Can the AIML/SRAI resolver pass a typed model request into the model manager? | **No. `model://` is a label, not a route.** | `model://` appears only in `runtime_tree.py` as graph node identifiers (`model://<name>`, `binds_to`, `prefers`). Nothing parses it, and nothing dispatches it to a backend. |

There is also **no `AGENT.md`** in this tree: no agent declaration file with identity, persona, parent Micronaut or model preferences exists yet.

## What does exist, and is already sound

- **Capability side.** `micronaut_host_handlers.HandlerHost` holds a registry of handlers with typed input/output schemas and `effect: read_only`. `micronaut_server.Engine.invoke_micronaut(uri, payload, from_uri=...)` resolves one URI, checks admission, and invokes it. That is the bounded operation the architecture describes, and it works.
- **Language side.** `aiml_graph` parses categories into typed segments with an `srai` child; `srai_resolver.resolve()` follows redirects with a depth limit and returns a trace. That is deterministic routing, and it works.
- **Model side.** Three registered backends (`advisor`, `worker`, `planner`) with aliases, lifecycle leases and a warm/cold state (`model_lifecycle`, `inference_session`). That is the model manager, and it works.
- **Phase side.** `phase_events` observes Pop, Wo, Yax, Sek, Ch'en and Xul around real handlers: routing, turn classification, composition, and the model turn.

## The gap, precisely

Three working components and no wire between them:

```
AIML/SRAI  ---X--->  capability invocation      (nothing calls Engine.invoke_micronaut from AIML)
AIML/SRAI  ---X--->  model dispatch             (model:// is a graph label, not a route)
AGENT.md   ---X--->  anything                   (the file does not exist)
```

A resolved SRAI template that renders `model://qwen3-1.7b` today produces **a string in an answer**. It does not call Qwen. SRAI redirects text into the matcher; it does not invoke anything, which is the distinction the review draws.

## The minimal bridge, if it is wanted

One host function, no new framework:

```
resolve_route(reply) -> None | {"scheme": "micronaut"|"model", "target": str, "payload": dict}

micronaut:  target is a handler URI  -> Engine.invoke_micronaut(uri, payload)   -> typed result
model:      target is a backend alias -> session_profile.complete(base_url, ...) -> candidate text
```

Then a turn becomes: AIML match → SRAI resolve → `resolve_route` → invoke → typed result → back into the
conversation as context, with Ch'en validating the typed result before Xul emits anything.

Four decisions to make before writing it, none of which this document assumes:

1. **Which URI form names a model** - `model://qwen3-1.7b` as a scheme handled by `resolve_route`, or an AIML route
   that already exists in the corpus.
2. **Who authorizes the invocation** - `invoke_micronaut` needs `granted` capabilities; a turn's grants come from
   capability groups today, not from a persona.
3. **Whether persona may widen grants** - the architecture says it must not; a guard should say so in code.
4. **What an `AGENT.md` schema is** - identity, parent, persona, model preferences. Nothing depends on it yet, and
   inventing a schema before the bridge exists would be one more declaration without a consumer.

## What this document does not claim

It does not claim the bridge is half-built. It is not built at all: the parts on both sides are real and tested, and
nothing connects them. That is a better position than it sounds - the missing piece is a dispatch function with four
inputs, not another subsystem.
