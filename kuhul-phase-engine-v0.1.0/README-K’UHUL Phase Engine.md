# K’UHUL Phase Engine

A standalone, **declarative** AIML/SRAI phase-contract repository assembled from the original uploaded files. All original AIML and CSS assets are copied unchanged.

## Six-phase cycle

`Pop → Wo → Yax → Sek → Ch’en → Xul → Pop`.

- **Pop**: ingress, lexical activation, retrieval
- **Wo**: state, constraints, decomposition
- **Yax**: candidate discovery and composition
- **Sek**: computation and transformation proposals
- **Ch’en**: verification and invariants
- **Xul**: authorized closure and persistence

The source routing file describes the boundary as **Sek proposes, Ch’en proves, XCFE authorizes, Xul commits**; it also distinguishes FOLD from Xul.

## Layout

- `phases/`: original six phase AIML files
- `routing/kuhul-phases.aiml`: original universal routing declarations
- `routing/xcfe.aiml`: original XCFE proposal declaration
- `integrations/daemon-modes.aiml`: original behavior mode declarations
- `styles/`: original relational graph stylesheet
- `manifest.json`: phase ordering, file paths, SHA-256 digests
- `schemas/`: manifest JSON Schema
- `tests/`: static XML/manifest checks (no executable dispatch)

## Validation

From repository root:

```sh
python -m unittest discover -s tests -v
```

These tests verify XML parsing, source integrity, phase membership and report pattern collisions. **They do not prove host SRAI resolution, XCFE authorization, runtime handler execution or GPU dispatch.** Pattern collisions are reported for loader integration; the host must define precedence before loading all files together.

## Integration contract

The host may load AIML categories as **data-only candidates**. Resolve SRAI through its existing loader; do not add a second compiler. Gate any tool call, GramStore mutation, model training or checkpoint export through host-side XCFE admission, verification and one-use authorization where applicable. The AIML files themselves do not grant permissions.

## Status

`v0.1.0` is a packaging baseline, not a certified executable engine. The original files are retained byte-for-byte; new schema and tests are repository scaffolding.

## License

No license has been selected. Add a LICENSE file after choosing public reuse terms.
