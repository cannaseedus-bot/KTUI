# K'UHUL Micronaut Grammar v1

**Status:** Proposed, testable grammar contract. This package is **not** a claim that the existing v0.3 C++ VM parses `.micronaut`, JSON Micronaut declarations, or XML Micronaut declarations. The v0.3 executor is a hardwired six-phase scaffold.

## Files
- `grammar/micronaut.ebnf`: human-readable syntax specification.
- `grammar/micronaut.peg`: Peggy-style executable-grammar source (requires a Peggy generator; not tested with Peggy here).
- `schema/micronaut.schema.json`: canonical JSON declaration validation, Draft 2020-12.
- `schema/micronaut.xsd`: XML serialization validation. XML is an alternative transport, not the runtime DOM.
- `schema/semantic-key.schema.json`: JSONL record contract compatible with the v0.3 example loader.
- `schema/relational-graph.contract.json`: describes supported GML field names; not a GML parser.
- `registry/opcodes.json`, `registry/phase-contract.json`: vocabulary and phase mapping.
- `examples/`: corresponding JSON, XML and text DSL examples.
- `tests/validate.py`: tests JSON Schema and XSD and rejects invalid samples.

## Design boundaries
1. Micronaut is a **declaration**, not an independent executor or sandbox.
2. `graph` points to relational data. Graph edges are data, never automatically executed.
3. `gate XCFE` preserves the previously discussed declaration syntax; its booleans are **metadata** and do not grant access, verify runtime behavior, or implement authorization. XCFE expression evaluation is separate.
4. `phase Chen` in the text DSL and XML corresponds to canonical runtime phase `Ch'en` in JSON. This is a spelling normalization, not a seventh phase.
5. `capability` declares a requested kind of operation; the host sandbox must separately grant it. `PATCH` and I/O must not run solely because a declaration contains them.
6. SRAI redirect is exact-key and bounded to depth 3 in v0.3; wildcards and recursive pattern engines are not specified as working.
7. PI is graph scoring/traversal vocabulary, not a proof of a complete multihop algorithm.
8. JSON schema validates *shape*, not graph reachability, resource existence, type inference, handler availability, or phase sequencing. A compiler/binder must check these separately.
9. No implicit execution: compile -> bind -> verify -> execute only with explicitly provided host capabilities.

## Integration targets
- A frontend parses one of the three serializations into the canonical JSON declaration AST.
- A semantic checker validates unique IDs, six-phase order, binding types, declared capabilities, GML node references, operator arity and host grants.
- An emitter maps each operation to a **registered existing C++ handler**. Reject unknown/unimplemented handlers, never silently simulate them.
- Keep JSONL and GML outside executable code; pass a bounded field window to the Micronaut.

## Run tests
`python tests/validate.py` (requires `jsonschema` and `lxml`).

## Known limitations
- PEG source is a proposed Peggy grammar and its semantic actions are not independently executed by this package.
- XSD covers the XML example and common declaration elements; it does not express the full JSON Schema condition object or all enum constraints for capability/type. Use canonical JSON schema + semantic checks for stricter validation.
- JSON phase name uses `Ch'en`, while text/XML use `Chen` for simple identifier grammar.
- No claim of full EBNF/PEG equivalence without parser differential tests.

## C++ grammar frontend
`compiler/grammar.cpp` and `compiler/grammar.h` implement a C++17 lexer, recursive-descent parser and structural checker for the v1 `.micronaut` DSL. It returns a typed `MicronautDecl` AST, without executing any declared operations. `compiler/grammar_main.cpp` is a CLI and `compiler/test_grammar.cpp` tests rejection of invalid opcodes and phase order.

Build: `cmake -S compiler -B build && cmake --build build && ctest --test-dir build --output-on-failure`.
Run: `build/micronaut-parse examples/dog.micronaut` (on Windows use the executable in the chosen build configuration).

**Limits:** Not a PEG-generator implementation, JSON/XML frontend, KSCX emitter, GML resolver or runtime dispatcher. `gate XCFE` flags are parsed as declaration metadata only. Structural checks do not grant capabilities or verify referenced graph files. No implicit execution.
