graph [
  label "matmul_contract"
  directed 1
  schema "gml/2"
  authority "data_only"
  admission "xcfe_required"
  parameter_ref "external://parameters/matmul-rhs"
  node [ id 0 label "lhs" kind "buffer" rank 2 shape "M,K" dtype "f32" buffer_role "input" ]
  node [ id 1 label "rhs" kind "buffer" rank 2 shape "K,N" dtype "f32" buffer_role "parameter" ]
  node [ id 2 label "matmul" kind "operator" opcode "MATMUL" requires "compute.matmul" ]
  node [ id 3 label "result" kind "buffer" rank 2 shape "M,N" dtype "f32" buffer_role "output" ]
  edge [ source 0 target 2 relation "input" port "lhs" ]
  edge [ source 1 target 2 relation "input" port "rhs" ]
  edge [ source 2 target 3 relation "output" port "result" ]
]
