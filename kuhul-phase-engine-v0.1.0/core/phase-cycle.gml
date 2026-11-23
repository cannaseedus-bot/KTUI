graph [
  label "phase_cycle"
  directed 1
  schema "gml/2"
  authority "data_only"
  admission "xcfe_required"
  node [ id 0 label "ingress" kind "boundary" phase "Pop" ]
  node [ id 1 label "bind" kind "boundary" phase "Wo" ]
  node [ id 2 label "candidate" kind "boundary" phase "Yax" ]
  node [ id 3 label "synchronize" kind "boundary" phase "Sek" ]
  node [ id 4 label "verify" kind "boundary" phase "Ch_en" ]
  node [ id 5 label "close" kind "boundary" phase "Xul" ]
  edge [ source 0 target 1 relation "phase_next" ]
  edge [ source 1 target 2 relation "phase_next" ]
  edge [ source 2 target 3 relation "phase_next" ]
  edge [ source 3 target 4 relation "phase_next" ]
  edge [ source 4 target 5 relation "phase_next" ]
  edge [ source 5 target 0 relation "phase_next" ]
]
