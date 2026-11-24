graph [ schema "aiml-gml/1" graph_id "composition/main" contract "composition"
  node [ id 6 kind "composition"
         output_type "paragraph"
         max_sentences 2
         attribute_order "alphabetical"
         separator ", "
         conjunction "and"
         subject_case "as recorded"
         sentence [ ordinal 0 template "{subject} is {attributes}." ]
         sentence [ ordinal 1 template "That is everything I have recorded about {subject}." ]
         note "A composition plan: subject, ordered attributes, and sentence templates. The slots may"
         note "only be filled from relations that exist; an unsupported attribute is a verification" ]
]
