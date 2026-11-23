# GML/2 separation package (migration draft)

This package **does not replace** your existing runtime or silently rewrite existing graphs. `legacy/` retains all 14 original files byte-for-byte; `overlays/` keeps domain-specific graphs explicitly classified as overlays. `core/` contains clean, reusable, data-only graph contracts.

## Binding rules
- `label` is presentation, never a provider lookup key.
- `requires` names a capability such as `compute.matmul`, not an assumed micronaut instance.
- `parameter_ref` and `buffer_role` are declarative references; weights and tensor bytes live outside GML.
- `cols` specifies feature width; `rank` specifies the number of tensor axes. Shape checking happens before binding/admission.
- Phase labels are descriptive; a node in Sek cannot authorize execution.
- `operator`/`opcode` are declarations; host registry resolves them. XCFE verifies capability, shape, provenance, authority, and permitted side effects before dispatch.
- The authoritative graph B is topology. Coordinates and probabilities are separate geometry/parameter overlays. Preserve original topology hashes for topology-only migrations.
- Never reinterpret `static_weight` as a universal probability. For n-grams it may be frequency, but general graphs need typed weight semantics, normalization scope and provenance.

## Migration order
1. Parse and inventory each original file, keeping node/edge IDs and graph structure.
2. Classify as core topology, domain overlay, binding manifest, parameter metadata or fixture.
3. Move provider identities and literal domain tokens to overlays, preserving old files until their consumers migrate.
4. Bind generic capabilities by contract; fail closed on missing implementations.
5. Validate structure, shapes, operator/dataflow contracts, provenance and XCFE admission separately.
6. Compare structural and semantic hashes before switching consumers; test existing CCC, Q3/Q4, CFPC and wildcard workflows.

`core/` is an architectural prototype, not a claim of compatibility with every existing GML parser. New attributes require a versioned validator and consumer migration.
