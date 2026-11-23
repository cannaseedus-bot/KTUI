graph [
  schema "gml-registry/1"
  graph_id "registry/gml-tensor"
  extension [ schema_id "gml-tensor/1" owner "gml.tensor" ]
  contract [ name "tensor_source" required "graph_id" required "tensor" ]
  contract [ name "tensor_assembly" required "graph_id" required "tensor" required "slice" ]
  field [ path "tensor" name "rank" type "integer" required_value 2 required 1 ]
  field [ path "tensor" name "shape" type "block" required 1 required_fields "rows,cols" ]
  field [ path "tensor.shape" name "rows" type "positive_integer" required 1 ]
  field [ path "tensor.shape" name "cols" type "positive_integer" required 1 ]
  field [ path "tensor" name "dtype" type "enum" values "float32" required 1 ]
  field [ path "tensor" name "layout" type "enum" values "row_major" required 1 ]
  field [ path "slice" name "source_ref" type "graph_uri" required 1 ]
  field [ path "slice" name "row_offset" type "nonnegative_integer" required 1 ]
  field [ path "slice" name "col_offset" type "nonnegative_integer" required 1 ]
  operator [ name "ASSEMBLE" signature "slices,shape -> tensor_plan" authority "declaration_only" ]
]
