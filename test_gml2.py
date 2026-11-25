import unittest
from gml2 import parse, serialize, GMLSyntaxError

SAMPLES = {
'pattern': 'node [ id 1 kind "pattern" expression "WHO IS *" wildcard_count 1 ]',
'template': 'node [ id 2 kind "template" segment [ ordinal 0 kind "text" value "WHAT IS " ] segment [ ordinal 1 kind "capture" index 1 ] ]',
'category': 'node [ id 0 kind "category" category_id "category:001" ] edge [ source_ref "aiml://categories/main#0" target_ref "aiml://patterns/main#1" verb "@has_pattern" ]',
'srai': 'node [ id 3 kind "srai" expression "WHAT IS {star:1}" max_depth 3 visited_guard 1 requires [ capability "pattern_index.lookup" signature "string -> pattern_candidates" ] ]',
'retrieval': 'node [ id 10 kind "vector_ref" vector_row 417 manifest "pattern-manifest-v3" scoring "cosine" ]',
'composition': 'node [ id 20 kind "composition" structure "paragraph" ordering [ item "relation:a" item "relation:b" ] ]',
}
class Tests(unittest.TestCase):
    def test_six_contracts(self):
        for name, body in SAMPLES.items():
            with self.subTest(name=name):
                doc = parse('graph [ schema "aiml-gml/1" contract "'+name+'" '+body+' ]')
                encoded = serialize(doc)
                self.assertEqual(parse(encoded), doc)
                self.assertEqual(serialize(parse(encoded)), encoded)
    def test_repeated_attributes(self):
        doc = parse('graph [ node [ id 1 ] node [ id 2 ] ]')
        self.assertEqual(len(doc.entries), 2)
    def test_comments(self):
        self.assertEqual(parse('graph [ (* comment *) id 2 ]'),parse('graph [ id 2 ]'))
    def test_reject_invalid(self):
        for src in ['graph [ id foo ]','graph [ id 1 ] junk','graph [ node [ id 1 ]','graph [ id 1.2.3 ]']:
            with self.subTest(src=src), self.assertRaises(GMLSyntaxError):
                parse(src)
    def test_escapes(self):
        doc = parse(r'graph [ label "a\n\"b" ]')
        self.assertEqual(parse(serialize(doc)),doc)
if __name__ == '__main__': unittest.main()
