# ASX Enterprise Intelligence Graph — demonstration package

A concrete **declaration-only** GML graph of an example corporation, with departmental, supplier, component, product, market, customer, financial, risk and regulatory relationships.

## Contents
- `graphs/enterprise.gml`: enterprise graph, 18 nodes and 21 directed edges.
- `contracts/enterprise-contract.json`: example schema and operator/authority declarations.
- `contracts/aiml-routes.xml`: example AIML/SRAI intent routing declarations; **not connected to the host AIML bundle**.
- `data/market-observations.jsonl`: synthetic shipping-cost observations.
- `graphs/shipping-impact.khl`: proposed K'UHUL phase workflow, not executed.
- `enterprise_graph.py`: isolated, deliberately narrow read-only demonstration inspector and scenario calculator; **not** a GML/2 parser, XCFE validator, or host integration.
- `tests/test_graph.py`: isolated demonstration tests.

## Try it
```sh
python enterprise_graph.py validate
python enterprise_graph.py impact
python -m unittest discover -s tests -v
```

The 15% shipping-cost scenario uses an illustrative $10/unit base shipping cost and synthetic exposure multipliers of 2 for Product A and 1 for Product B. The resulting $3 and $1.50 changes are **unit-cost deltas**, not forecast margins or company financials.

## Integration boundary
This package does **not** modify the user's repository or claim to conform to its actual `gml2` loader. The syntax and schema are a proposed extension. Before host integration, map these declarations to the installed registry, implement typed field contracts and cross-graph resolution, route AIML through the existing `aiml_bundle.py`, and keep XCFE admission and persistence authorization external to the graph. The JSONL file is illustrative observation data, not a user database.

## kuhul-phases/v1 manifests (one JSON file per phase)

A phase does not need a `.khl` program or a `.aiml` file to be useful: it can be a JSON manifest, and
the six manifests can **chain by schema URI**.

```json
{
  "schema": "kuhul-phases/v1",
  "phase": "Sek",
  "uri": "kuhul://phases/sek",
  "aiml": ["../sek.aiml"],
  "bindings": [
    {"pattern": "TELL ME ABOUT MY DOG", "directive": "COMPOSE pet",
     "capability": "graph.relations.read"}
  ],
  "next": "kuhul://phases/chen",
  "authority": "declaration_only"
}
```

`aiml` names pure AIML banks; `bindings` are AIML bindings - a pattern that redirects (`{"pattern":
"WHO IS *", "srai": "WHAT IS {star:1}"}`) or that emits a host directive. `next` chains to the next
phase by URI, resolved inside the manifest set: `kuhul://phases/<name>` -> `<dir>/<name>.json`.

The loader (`core/phase_manifest.py`) regulates the format and nothing else:

| check | behaviour |
|---|---|
| schema id | must be `kuhul-phases/v1` |
| phase | must be one of the six (`Chen` and `Ch'en` both accepted) |
| uri | if declared, it must agree with the phase |
| `aiml` | a missing file is reported, never assumed |
| `bindings` | needs a target; `{star:N}` may not exceed the pattern's wildcards |
| `next` | followed by schema URI; unknown schemes are errors |
| chain | cycles, repeated phases and over-long chains are bounded failures with the chain printed |

Try it from the package directory:

```powershell
python core/phase_manifest.py phases/json
# kuhul-phases/v1 chain: Pop -> Wo -> Yax -> Sek -> Ch'en -> Xul (6 manifest(s), 6 aiml file(s), 5 binding(s))
```

The manifests in `phases/json/` chain all six phases and point at the existing banks. Loading says what
exists; it does not populate a kernel, execute an instruction or admit anything, and the report says
`authority: declaration_only`.

## K'UHUL program layer (parse, validate, trace)

`core/program.py` implements the grammar in `grammar/kuhul-grammar.ebnf`: declarations
(`glyph NAME = "…"`, `relation NAME = "…"`), instructions (`map`, `filter`, `fold`, `reduce`, `sync`,
`emit`, `verify`, `dispatch`), phase blocks, lane blocks (`lane risk : Graph { … }`), bindings
(`bind ⟁A -> B`) and `⟁glyph` references.

```text
glyph DATA = "enterprise:records"      # the grammar declares by identifier...
lane risk : Graph { map(⟁DATA) }       # ...and references it with the glyph mark

Pop { … }  Wo { … }  Yax { … }  Sek { … }  Chen { … }  Xul { … }

Ch'en { verify("provenance,units,coverage,permissions") }    # Chen and Ch'en both parse
```

Validation is separate from parsing and covers what the parser cannot: the opcode vocabulary, argument
arity, lane types, unresolved `⟁glyphs` and unknown references.

**Phases are a vocabulary, not a schedule.** Which of the six a program uses - and in which order - is
the program's business, because a phase is meaningful only for the work it does. `Wo { … }` on its own
is valid, and so is `Xul { … } Pop { … }`. The report records what was used (`phases`), the canonical
equivalent (`canonical`) and how they relate (`order`: `canonical` / `subset` / `as-written`); only an
unknown phase *name* is an error. A caller that wants the canonical sequence enforced asks for it with
`validate(program, strict_order=True)`.

XML is not required either: the call grammar and the bracket dialect are the two accepted forms, and
the phases work in both without any markup layer.

**Nothing here executes.** `evaluate()` walks the program in phase order and records each step with its
resolved arguments and its declared effect. A step whose implementation is not bound is recorded as
`deferred` with the reason; a step that raises records the error. A trace carries
`execution: false`, `mutation: false`, `authority: "host"`.

The bracket dialect ships too - `graphs/shipping-impact.khl` parses through `parse_khl()` into the same
AST, so the existing example is executable as a *structure* rather than unreadable text.

## EmbeddingGemma2 AIML vector adapter (read-only)

`adapters/embeddinggemma2.py` loads existing EmbeddingGemma2 `.npy` arrays as memory maps, checks that the three lanes share one rank-2 float32 shape, and validates the JSONL bindings. It performs chunked cosine ranking and returns the associated AIML pattern/template record. It does not embed raw text, compile AIML, resolve SRAI, write to the enterprise graph, or grant XCFE admission.

**The producer's pair schema is now verified against the real assets** (the earlier version of this
section said the JSONL structure had not been inspected):

```
rows        99,524      dimensions  256      dtype float32
vectors     pattern_vectors.f32.npy · template_vectors.f32.npy · category_vectors.f32.npy (100 MB each)
bindings    aiml_pattern_template_pairs.jsonl (52 MB, 1.7 s to parse)
record      {"index": n, "A": {"vector_row": n}, "B": {"vector_row": n}, "cosine_similarity": …,
             "pattern": …, "that": …, "topic": …, "template": …, "authority": "data_only"}
```

The row of a record is its `index`, and `A.vector_row`/`B.vector_row` must agree with it - a record that
contradicts itself is a contract error rather than a silent guess. Coverage must equal the vector count.

**Ranking is not authorization.** The adapter exposes the separation the architecture requires:

| surface | what it does | what it never does |
|---|---|---|
| `retrieve(query_vector)` | chunked cosine over one lane | admit, execute or persist |
| `retrieve_by_row(row)` | nearest neighbours of an existing row, no encoder needed | embed text |
| `lookup(text)` | exact pattern lookup (`WHO IS *`, not `who is saturn`) | pretend an unseen phrase has a vector |
| `for_text(text)` | exact hit, then its neighbours; `NO_ENCODER_MATCH` otherwise | fabricate an embedding |
| `compatible(pattern, text)` | AIML wildcard compatibility - can the pattern bind the input at all | score anything |
| `rank_and_filter(text)` | keeps compatible candidates, reports the dropped ones | let a high score bypass structure |

A measured example on the real data - `rank_and_filter("what is ai")` keeps row 1 (`WHAT IS AI`,
score 1.0) and **drops** rows 88,107 / 88,466 / 93,242 (`WHAT IS A AI`, `WHAT IS AN AI`,
`WHAT IS AN ARTIFICIAL INTELLIGENCE`): semantically close, structurally unable to bind the input. Every
candidate still carries `admission: PENDING_XCFE`.

Install `numpy` and run from this package directory:

```powershell
python -m pip install numpy
python adapters/embeddinggemma2.py --vectors 'C:\Users\canna\.aiml\aiml-embeddinggemma2-vectors' validate
python adapters/embeddinggemma2.py --vectors 'C:\Users\canna\.aiml\aiml-embeddinggemma2-vectors' retrieve --query-vector query-vector.json --lane pattern --top-k 5
python -m unittest discover -s tests -v
```

`query-vector.json` must contain a JSON array of **256 floats generated by the same EmbeddingGemma2
encoder**; a phrase that is not already a known pattern comes back as `NO_ENCODER_MATCH` rather than a
fabricated embedding. Graph proposals from `propose_graph_bindings` stay `declaration_only` and
`PENDING_XCFE`: the adapter produces candidates, and the host decides.

The example enterprise graph remains a separate read-only demonstration; host `aiml_bundle.py`/`planner.py`/`functions.py` integration is not claimed.
