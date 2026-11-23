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
