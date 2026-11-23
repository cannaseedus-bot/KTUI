graph [
  schema "gml-math/1"
  graph_id "math/matmul"
  directed 1
  node [ id 0 kind "tensor" role "input" rank 2 rows "M" cols "K" ]
  node [ id 1 kind "tensor" role "weight" rank 2 rows "K" cols "N" ]
  node [ id 2 kind "operator" opcode "MATMUL" signature "[M,K],[K,N] -> [M,N]" requires [ capability "gml.tensor.matmul" signature "matrix,matrix -> matrix" ] ]
  node [ id 3 kind "tensor" role "output" rank 2 rows "M" cols "N" ]
  edge [ source 0 target 2 verb "@input" ]
  edge [ source 1 target 2 verb "@input" ]
  edge [ source 2 target 3 verb "@output" ]
]
