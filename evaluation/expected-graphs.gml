graph "eval-corpus" {
  attribute "schema" = "kuhul-eval-graphs/1";
  attribute "authority" = "declaration_only";
  node "pair-01" {
    attribute "category" = "operator_pair";
    attribute "phase" = "Sek";
    attribute "review" = "frozen";
    node "filter#0" { attribute "operator" = "filter"; }
    node "map#0" { attribute "operator" = "map"; }
    edge "filter#0" -> "map#0";
    attribute "target" = "graph.matches";
  }
  node "pair-02" {
    attribute "category" = "operator_pair";
    attribute "phase" = "Sek";
    attribute "review" = "frozen";
    node "filter#0" { attribute "operator" = "filter"; }
    node "map#0" { attribute "operator" = "map"; }
    edge "filter#0" -> "map#0";
    attribute "target" = "graph.matches";
  }
  node "chain-01" {
    attribute "category" = "full_composition";
    attribute "phase" = "Sek";
    attribute "review" = "frozen";
    node "filter#0" { attribute "operator" = "filter"; }
    node "map#0" { attribute "operator" = "map"; }
    node "fold#0" { attribute "operator" = "fold"; }
    node "reduce#0" { attribute "operator" = "reduce"; }
    node "accumulate#0" { attribute "operator" = "accumulate", parent = "fold#0"; }
    edge "filter#0" -> "map#0";
    edge "map#0" -> "fold#0";
    edge "fold#0" -> "reduce#0";
    edge "fold#0" -> "accumulate#0";
    attribute "target" = "graph.matches";
  }
  node "chain-02" {
    attribute "category" = "full_composition";
    attribute "phase" = "Sek";
    attribute "review" = "reviewed";
    node "filter#0" { attribute "operator" = "filter"; }
    node "map#0" { attribute "operator" = "map"; }
    node "fold#0" { attribute "operator" = "fold"; }
    node "reduce#0" { attribute "operator" = "reduce"; }
    node "accumulate#0" { attribute "operator" = "accumulate", parent = "fold#0"; }
    edge "filter#0" -> "map#0";
    edge "map#0" -> "fold#0";
    edge "fold#0" -> "reduce#0";
    edge "fold#0" -> "accumulate#0";
    attribute "target" = "graph.matches";
  }
  node "phase-01" {
    attribute "category" = "phase_selection";
    attribute "phase" = "Wo";
    attribute "review" = "frozen";
    node "map#0" { attribute "operator" = "map"; }
    attribute "target" = "graph.matches";
  }
  node "phase-02" {
    attribute "category" = "phase_selection";
    attribute "phase" = "Ch'en";
    attribute "review" = "draft";
    node "filter#0" { attribute "operator" = "filter"; }
    attribute "target" = "graph.matches";
  }
  node "authority-01" {
    attribute "category" = "authority";
    attribute "phase" = "Ch'en";
    attribute "review" = "frozen";
    attribute "refusal" = "capability_not_granted";
  }
  node "authority-02" {
    attribute "category" = "authority";
    attribute "phase" = "Ch'en";
    attribute "review" = "frozen";
    attribute "refusal" = "capability_not_granted";
  }
  node "unknown-01" {
    attribute "category" = "unknown_facts";
    attribute "phase" = "Xul";
    attribute "review" = "frozen";
    attribute "refusal" = "no_records";
  }
  node "unknown-02" {
    attribute "category" = "unknown_facts";
    attribute "phase" = "Xul";
    attribute "review" = "draft";
    attribute "refusal" = "no_records";
  }
  node "uri-01" {
    attribute "category" = "uri_binding";
    attribute "phase" = "Yax";
    attribute "review" = "frozen";
    node "filter#0" { attribute "operator" = "filter"; }
    attribute "target" = "gml://relations";
  }
  node "uri-02" {
    attribute "category" = "uri_binding";
    attribute "phase" = "Pop";
    attribute "review" = "reviewed";
    node "map#0" { attribute "operator" = "map"; }
    attribute "target" = "kuhul://phases/sek";
  }
}
