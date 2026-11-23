graph [
  label "tensor_width_contracts"
  directed 1
  schema "gml/2"
  authority "data_only"
  admission "xcfe_required"
  comment "Widths are feature dimensions, not tensor ranks. Projection requires declared parameters."
  node [ id 0 label "width_2" kind "tensor_shape" rank 2 rows "symbolic:B" cols 2 dtype "f32" layout "row_major" ]
  node [ id 1 label "width_4" kind "tensor_shape" rank 2 rows "symbolic:B" cols 4 dtype "f32" layout "row_major" ]
  node [ id 2 label "width_8" kind "tensor_shape" rank 2 rows "symbolic:B" cols 8 dtype "f32" layout "row_major" ]
  node [ id 3 label "width_12" kind "tensor_shape" rank 2 rows "symbolic:B" cols 12 dtype "f32" layout "row_major" ]
  node [ id 4 label "width_24" kind "tensor_shape" rank 2 rows "symbolic:B" cols 24 dtype "f32" layout "row_major" ]
  node [ id 5 label "width_48" kind "tensor_shape" rank 2 rows "symbolic:B" cols 48 dtype "f32" layout "row_major" ]
  edge [ source 0 target 1 relation "projects_to" operator "MAP" ]
  edge [ source 1 target 2 relation "projects_to" operator "MAP" ]
  edge [ source 2 target 3 relation "projects_to" operator "MAP" ]
  edge [ source 3 target 4 relation "projects_to" operator "MAP" ]
  edge [ source 4 target 5 relation "projects_to" operator "MAP" ]
]
