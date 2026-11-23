# K-UHUL Heuristic Grammar Extension v1.0

Copy the four files in `references/` to `C:\Users\canna\.codex\skills\kuhul\references\`.

This is a proposed extension, not a verified modification of existing grammar or runtime. Before integration, compare `identifier`, `type_ref`, phase productions and operator signatures with existing EBNF; reuse canonical nonterminals instead of duplicating them. Keep existing XCFE node classes unchanged.

## Example

```text
heuristic field_rank {
  input: Lane<Candidate>;
  output: Lane<Candidate>;
  objective: maximize score;
  mode: seed;
  feature W: Scalar;
  feature C: Scalar;
  feature R: Scalar;
  score: W * C * R;
  select: top_k(3);
}
optimization field_search {
  heuristic: field_rank;
  strategy: seeded;
  optimizer: bounded_search;
  budget: 64;
  verify: candidate_constraints;
}
route field_search {
  pop: ingress;
  wo: bind_context;
  yax: rank_candidates;
  sek: admitted_optimizer;
  chen: verify_constraints;
  xul: authorized_closure;
}
```

Validation needed: parse the example with a combined grammar, verify type/mode agreement and XCFE admission, run existing conformance tests. The EBNF alone does not enforce cross-field rules.
