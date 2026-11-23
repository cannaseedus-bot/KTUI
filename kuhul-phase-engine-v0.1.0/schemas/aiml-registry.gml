graph [
 schema "gml-registry/1"
 graph_id "registry/aiml-gml"
 extension [ schema_id "aiml-gml/1" owner "gml.aiml" ]
 resolver [ scheme "aiml" kind "node_addressable" ]
 resolver [ scheme "gml" kind "whole_graph" ]
 constraint [ name "pattern_wildcard_count" predicate "wildcard_count_matches" arity 2 scope "node" authority "declaration_only" ]
 constraint [ name "srai_static_only_if_literal" predicate "srai_static_ok" arity 1 scope "node" authority "declaration_only" ]
 constraint [ name "srai_safeguards_declared" predicate "srai_guards_present" arity 1 scope "node" authority "declaration_only" ]
 constraint [ name "template_ordinals" predicate "template_ordinals_contiguous" arity 1 scope "node" authority "declaration_only" ]
 constraint [ name "template_capture_bounds" predicate "template_capture_in_range" arity 2 scope "node" authority "declaration_only" ]
 constraint [ name "endpoint_mode" predicate "endpoint_modes_consistent" arity 1 scope "bundle" authority "declaration_only" ]
]
