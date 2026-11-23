# GML/2 tensor assembly — gml.tensor/1

A dependency-free, **declarative** tensor-slice assembler built on the existing GML/2 portable parser (`core/gml2.py`). This package is an additive extension: it does not modify GML/2 grammar or AIML/GML.

## Contracts
- `tensor_source`: one file declares a rank-2 row-major float32 matrix block, including a column, row, or multiple rows. Inline `data [ value ... ]` is optional for plan-only validation.
- `tensor_assembly`: one file declares an output matrix and multiple `slice` blocks with `source_ref`, `row_offset`, and `col_offset`.
- `gml://<graph_id>` addresses whole source graphs; `aiml://...#node` remains the distinct AIML node-addressing convention.
- Each source block occupies a rectangle. Assembly rejects missing references, duplicate graph IDs, shape mismatch, non-finite inline values, out-of-bounds slices and overlaps. Complete coverage is the default; `coverage_policy "sparse"` allows gaps (represented as `None` if materialized).
- The registry is a **declarative draft**, not yet a self-hosted schema validator.

## Run

```bash
python -m unittest discover -s tests -v
python core/assemble.py contracts tensor/assembled --materialize
```

Expected output matrix (6 rows x 2 columns):
```
1  5
2  6
3  7
4  8
9 10
11 12
```

## Boundaries
This is a rank-2, float32, row-major assembly **prototype**. It does not implement higher-rank stacking, strides, transposition, external binary buffers, matrix multiplication, GPU dispatch, GML micronaut execution, phase routing, or XCFE admission. The `gml.tensor` owner identifier is a contract namespace, not a preinstalled runtime implementation. Materialization is a pure in-memory transformation of explicitly supplied values, not an authorized runtime side effect.


## v2 hardening
- All tensor sources are validated eagerly on directory load; duplicate graph identities rejected.
- Registry-driven field presence/type/enum checks use `schemas/tensor-registry.gml`; missing mandatory declarations fail closed. Specialized shape/data/coverage checks remain in `assemble.py`.
- Shared URI scheme dispatch in `core/resolvers.py`; `gml://` resolves whole graphs, `aiml://` resolves node addresses (not used by tensor assembler).
- Materialization preflights every referenced source before writing to its local output buffer.
- Rank 2, row-major float32 remain the only supported assembly layout. No kernel execution or XCFE admission.

Run: `python -m unittest discover -s tests -v` from this package directory.


## v3 registry enforcement
The bootstrap registry now rejects unknown tensor, shape, and slice attributes, unsupported field types, and rank values other than the registry-declared `required_value 2`. `assemble()` checks the registered assembly fields even for direct callers. The parser and original graph fixtures remain unchanged. This is still a bounded bootstrap registry, not general-purpose self-hosting or XCFE admission.


## v3.2 rule dispatch
Six mandatory GML-declared constraints dispatch to fixed, pure Python predicates through `core/rules.py`. Missing/unknown declarations fail closed at registry load. Dtype enum now accepts float32 and float64 (numeric Python values; no binary float64 ABI promise). The GML grammar is unchanged. Registry bootstrap and predicate implementations remain Python; this is not self-hosting, execution admission, or GPU dispatch.

## v3.3 — structural rule dispatch

- `Registry.require(name)` is a production call-site gate, not a test-only assertion.
- Each GML `constraint` declares `arity` matching the trusted keyword-only predicate signature.
- `rules._PREDICATES` is private and only `rules.dispatch` calls implementations.
- `assemble.py` uses `registry.require(name).check(**context)` for all six rules.
- Missing rules and unknown predicates fail closed; GML never executes code.
- Arity counts keyword context parameters (not tensor rank or number of slices).
- This is not a sandbox, self-hosting GML evaluator, or XCFE admission.


## v3.4 shared extension interface

`core/extension.py` loads GML-declared constraints and resolver kinds into an immutable Extension. Each declaration must match a trusted, import-time-frozen predicate and its keyword-only arity. Unknown authority, predicate, scope, or resolver kind fails closed. The tensor registry now declares `resolver [ scheme "gml" kind "whole_graph" ]`. `assemble()` preflights all six required rule names before assembly. Existing tensor field validation remains in `registry.py` for backward compatibility; the extension interface is a reusable validation layer, **not** an AIML implementation or a self-hosted evaluator. The trusted Python predicate implementations are not a sandbox.

## v3.5 AIML/GML port

Adds `schemas/aiml-registry.gml`, six minimal contract fixture graphs,
`core/aiml_bundle.py`, and trusted AIML predicates in the immutable startup
allowlist. Both extensions load in either order: the predicate mapping was
already immutable at import in v3.4, so a mutable `finalize()` phase is
**not necessary**. No AIML rendering or SRAI execution is implemented.

Run `python -m unittest discover -s tests -v` from the package root.

## Merge ledger patch: F14 + M2 (2026-11-23)

- F14: `extension.owns_document` provides schema ownership; tensor `load_directory` skips validation of other schemas while preserving their documents for domain-specific validators.
- M2: `tensor-registry.gml` declares graph-level fields and `data.value`; validator rejects unknown graph/data keys, including `vaule`, and validates enum values. Repeated `data.value` entries remain legal.
- Four regression tests added. Standalone package: `python -m unittest discover -s tests -q` -> 57 tests, OK.
- This is **not** a patch to `kuhul-phase-engine-v0.1.0` (checkout unavailable). F1-F13, M3-M7, host `base_health`, `extension_summary`, `gml_*`, `-text`, and 67-test host suite were not verified here.

## F14.1 / M2.1 follow-up (standalone)
- `owns_document` rejects missing schema instead of treating it as foreign.
- `resolve(..., expected_schema=...)` checks the resolved graph's schema; tensor source references and AIML node/category references supply their respective expected schemas.
- Registry field `repeatable 1` explicitly permits repeated `data.value`; other fields default to nonrepeatable.
- Unknown graph-level and data-block fields report their scope.
- Six additional tests cover missing schema, repeated values, duplicate graph id, cross-schema rejection, same-schema resolution and repeatable declaration.
- Host checkout not included; no host tests or git changes performed. F14/M2 host merge remains unverified.
