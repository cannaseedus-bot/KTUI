graph [
  schema "gml-registry/1"
  graph_id "conversation/greeting"
  extension [ schema_id "gml-conversation/1" owner "knumatic.host" ]
  contract [ name "greeting-graph" required "node" required "edge" ]

  note "Greeting-µ: a greeting is an entry point, not an answer. This graph declares which"
  note "greetings exist, what each one may lead to, and which destinations need admission before"
  note "anything happens. It routes; it never authorizes."

  node [ id 1 kind "greeting" phrase "HELLO" meaning "open contact" ]
  node [ id 2 kind "greeting" phrase "HI" meaning "open contact" ]
  node [ id 3 kind "greeting" phrase "HEY" meaning "open contact, informal" ]
  node [ id 4 kind "greeting" phrase "GOOD MORNING" meaning "open contact, time-bound" ]
  node [ id 5 kind "greeting" phrase "YO" meaning "open contact, very informal" ]

  node [ id 6 kind "social" phrase "HOW ARE YOU" meaning "social check" ]
  node [ id 7 kind "social" phrase "WHATS UP" meaning "social check, informal" ]

  node [ id 8 kind "destination" name "conversation" authority "read_only"
         cues "" note "small talk, answered from the bank" ]
  node [ id 9 kind "destination" name "question" authority "read_only"
         cues "WHAT,WHO,WHY,HOW,WHEN,WHERE,WHICH" note "answered locally or by the model" ]
  node [ id 10 kind "destination" name "tool" authority "proposal_only"
         cues "CHECK,STATUS,DIFF,LOG,BRANCH,FILES,TIME,CONVERT,SEARCH,LOOK" note "read-only verbs" ]
  node [ id 11 kind "destination" name "command" authority "requires_grant"
         cues "RUN,EXECUTE,BUILD,COMMIT,PUSH,CLONE,SYNC" note "repo and process writes" ]
  node [ id 12 kind "destination" name "memory" authority "requires_grant"
         cues "REMEMBER,MY DOG,MY NAME,FORGET,ERASE" note "JSONL history behind /allow memory" ]
  node [ id 13 kind "destination" name "task" authority "read_only"
         cues "TASK,ADD TASK,TODO,DONE,START,BLOCK" note "the task bus" ]
  node [ id 14 kind "destination" name "identity" authority "read_only"
         cues "WHO ARE YOU,YOUR NAME,WHAT ARE YOU" note "the daemon's self-description" ]

  edge [ source 1 target 8 relation "leads_to" ]
  edge [ source 2 target 8 relation "leads_to" ]
  edge [ source 4 target 8 relation "leads_to" ]
  edge [ source 5 target 8 relation "leads_to" ]

  edge [ source 3 target 8 relation "leads_to" ]
  edge [ source 3 target 9 relation "may_lead_to" ]
  edge [ source 3 target 10 relation "may_lead_to" ]
  edge [ source 3 target 11 relation "may_lead_to" ]
  edge [ source 3 target 12 relation "may_lead_to" ]
  edge [ source 3 target 13 relation "may_lead_to" ]
  edge [ source 3 target 14 relation "may_lead_to" ]

  edge [ source 6 target 8 relation "leads_to" ]
  edge [ source 6 target 10 relation "may_lead_to" ]
  edge [ source 7 target 8 relation "leads_to" ]

  edge [ source 9 target 8 relation "leads_to" ]
  edge [ source 9 target 10 relation "may_lead_to" ]
  edge [ source 10 target 9 relation "may_lead_to" ]
  edge [ source 11 target 10 relation "may_lead_to" ]
  edge [ source 12 target 9 relation "may_lead_to" ]
  edge [ source 13 target 8 relation "leads_to" ]
  edge [ source 14 target 8 relation "leads_to" ]

  constraint [ name "no_grant_from_greeting" arity 2 scope "graph" predicate "greeting_grants_nothing"
               authority "declaration_only" ]
  constraint [ name "admission_before_write" arity 2 scope "node" predicate "authority_declared"
               authority "declaration_only" ]
  operator [ name "ROUTE" signature "utterance -> candidate*" authority "declaration_only" ]

  note "A greeting selects routes. Each candidate is a proposal; the host admits or refuses it."
]
