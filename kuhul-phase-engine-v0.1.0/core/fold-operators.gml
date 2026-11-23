graph [
  label "fold_operator_contract"
  directed 1
  schema "gml/2"
  authority "data_only"
  admission "xcfe_required"
  comment "Containment and dataflow are distinct. Execution requires external operator binding and XCFE admission."
  node [ id 0 label "source" kind "value" ]
  node [ id 1 label "filter" kind "operator" opcode "FILTER" ]
  node [ id 2 label "map" kind "operator" opcode "MAP" ]
  node [ id 3 label "fold" kind "operator" opcode "FOLD" ]
  node [ id 4 label "accumulate" kind "operator" opcode "ACCUMULATE" ]
  node [ id 5 label "reduce" kind "operator" opcode "REDUCE" ]
  node [ id 6 label "result" kind "value" ]
  edge [ source 0 target 1 relation "dataflow" ]
  edge [ source 1 target 2 relation "dataflow" ]
  edge [ source 2 target 3 relation "dataflow" ]
  edge [ source 4 target 3 relation "contained_by" ]
  edge [ source 3 target 5 relation "dataflow" ]
  edge [ source 5 target 6 relation "dataflow" ]
]
