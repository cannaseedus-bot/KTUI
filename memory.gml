graph [
  schema "gml-registry/1"
  graph_id "registry/knumatic-user-memory"
  extension [ schema_id "user-memory/1" owner "knumatic.host" ]

  contract [ name "memory_event" required "user_id" required "type" required "subject" required "predicate" ]
  contract [ name "memory_graph" required "graph_id" required "nodes" required "edges" ]

  field [ path "event" name "event_id" type "string" required 1 ]
  field [ path "event" name "user_id" type "string" required 1 ]
  field [ path "event" name "type" type "enum" values "fact_asserted,fact_retracted,erasure" required 1 ]
  field [ path "event" name "subject" type "string" required 0 ]
  field [ path "event" name "predicate" type "string" required 0 ]
  field [ path "event" name "value" type "string" required 0 ]
  field [ path "event" name "source" type "string" required 0 ]
  field [ path "event" name "status" type "enum" values "accepted,refused" required 0 ]

  field [ path "graph" name "node" type "block" required 1 ]
  field [ path "graph" name "edge" type "block" required 1 ]

  constraint [ name "identity_scope" arity 2 scope "event" predicate "identity_scope" authority "declaration_only" ]
  constraint [ name "append_only" arity 2 scope "event" predicate "append_only" authority "declaration_only" ]

  operator [ name "REMEMBER" signature "event -> memory_event" authority "declaration_only" ]
  operator [ name "ERASE" signature "user -> tombstone" authority "declaration_only" ]

  note "The JSONL event log is the history; this document describes its records. The GML projection"
  note "built from the log is a view, not a second authority. A matching pattern proposes a write;"
  note "the host admits it, and erasure overrides append-only history on request."
]
