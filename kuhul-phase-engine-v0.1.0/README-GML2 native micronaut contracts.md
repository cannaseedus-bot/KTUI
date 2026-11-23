# GML/2 native micronaut contracts — implementation starter

GML owns its micronaut capability identifiers (`gml.pattern.lookup`, `gml.vector.rank`, `gml.compose`, `gml.tensor.matmul`). No hardcoded external micronaut name is required. These are **requirements**, not executable implementations.

## Files
- `core/gml2.py`: preserved Step 1 GML parser/serializer.
- `core/validate.py`: read-only structural and host-binding checks.
- `core/bundle.py`: explicit `aiml://<graph_id>#<node_id>` resolver.
- `schemas/registry.gml`: bootstrap registry declarations (not yet a fully self-hosting schema validator).
- `contracts/{pattern,template,category,srai,retrieval,composition}.gml`: AIML/GML examples.
- `contracts/math.gml`: domain-independent tensor/matmul example.
- `tests/test_contracts.py`: round-trip, structural, binding and negative tests.

Run `python -m unittest discover -s tests -v` from the package root.

## Authority boundaries
The validator does not execute, dispatch, mutate or admit graphs. Missing host capabilities keep a graph `STRUCTURALLY_VALIDATED` with `missing_capabilities`. XCFE admission and Xul closure are not implemented.

## Remaining work before production
This starter **does not** implement complete schema-driven field validation, edge-role cardinalities, full template capture bounds across category references, URI percent-encoding/normalization, operator shape unification, recursive SRAI evaluation, or reference AIML round-trip conformance. `gml2.py` is the earlier prototype parser and is not claimed to be a full grammar conformance implementation. The registry is declarative data but not yet a self-hosting registry. No domain-specific word corpora are bundled.
