graph [ schema "aiml-gml/1" graph_id "retrieval/main" contract "retrieval"
  node [ id 5 kind "retrieval"
         strategy "lexical_then_recency"
         weight_lexical 0.7
         weight_recency 0.3
         min_score 0.10
         max_candidates 6
         source "user_memory.projection"
         note "Scores a relation on how many query words it shares (lexical) and how recently it was"
         note "asserted (recency). It ranks evidence; it never invents a relation to fill a slot." ]
]
