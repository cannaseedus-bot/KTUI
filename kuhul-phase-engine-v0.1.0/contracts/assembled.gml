graph [
  schema "gml-tensor/1"
  contract "tensor_assembly"
  graph_id "tensor/assembled"
  directed 1
  tensor [ rank 2 shape [ rows 6 cols 2 ] dtype "float32" layout "row_major" ]
  overlap_policy "reject"
  coverage_policy "complete"
  slice [ source_ref "gml://tensor/col_a" row_offset 0 col_offset 0 ]
  slice [ source_ref "gml://tensor/col_b" row_offset 0 col_offset 1 ]
  slice [ source_ref "gml://tensor/row_block" row_offset 4 col_offset 0 ]
]
