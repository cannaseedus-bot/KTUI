graph [
  schema "aiml-gml/1"
  graph_id "redirects/main"
  redirect_budget 3
  directed 1
  node [
    id 3
    kind "srai"
    expression "WHAT IS {star:1}"
    max_depth 3
    visited_guard 1
    requires [ capability "gml.pattern.lookup" signature "string -> pattern_candidates" ]
  ]
]
