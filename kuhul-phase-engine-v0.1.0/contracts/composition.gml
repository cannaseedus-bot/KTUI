graph [
  schema "aiml-gml/1"
  graph_id "composition/main"
  directed 1
  node [ id 20 kind "composition" structure "paragraph" constraint [ name "subject_consistency" ] constraint [ name "no_unsupported_detail" ] requires [ capability "gml.compose" signature "plan -> text" ] ]
]
