graph [
  schema "gml-registry/1"
  graph_id "registry/knumatic-ledger"
  extension [ schema_id "gml-crypto-ledger/1" owner "knumatic.host" ]

  contract [ name "ledger_entry" required "sequence" required "previous_hash" required "content_hash" required "kind" ]

  field [ path "entry" name "sequence" type "nonnegative_integer" required 1 ]
  field [ path "entry" name "previous_hash" type "string" required 1 ]
  field [ path "entry" name "content_hash" type "string" required 1 ]
  field [ path "entry" name "kind" type "string" required 1 ]
  field [ path "entry" name "timestamp" type "string" required 0 ]
  field [ path "entry" name "payload" type "block" required 0 ]
  field [ path "entry" name "signature" type "string" required 0 ]

  constraint [ name "chain_link" arity 2 scope "entry" predicate "chain_link" authority "declaration_only" ]
  constraint [ name "content_integrity" arity 2 scope "entry" predicate "content_integrity" authority "declaration_only" ]

  operator [ name "APPEND" signature "entry,head -> ledger_entry" authority "declaration_only" ]

  note "This document describes the audit ledger's record shape. It grants no authority: the ledger"
  note "is appended and verified by the host, and a valid record authorizes nothing."
]
