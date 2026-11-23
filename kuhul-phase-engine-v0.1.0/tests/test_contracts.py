import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'core'))
from gml2 import parse,serialize,Block,Attribute
from validate import validate
from bundle import load_bundle

class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry=parse((ROOT/'schemas/registry.gml').read_text())
        cls.bundle=load_bundle(ROOT/'contracts')
    def test_roundtrip(self):
        for path in (ROOT/'contracts').glob('*.gml'):
            with self.subTest(path=path.name):
                doc=parse(path.read_text()); self.assertEqual(parse(serialize(doc)),doc)
                self.assertEqual(serialize(parse(serialize(doc))),serialize(doc))
    def test_structural(self):
        for path in (ROOT/'contracts').glob('*.gml'):
            with self.subTest(path=path.name):
                result=validate(parse(path.read_text()),self.registry,self.bundle)
                self.assertEqual(result.state,'STRUCTURALLY_VALIDATED',result.failures)
    def test_unresolved_binding_not_rejected(self):
        doc=parse((ROOT/'contracts/srai.gml').read_text())
        result=validate(doc,self.registry,self.bundle,{})
        self.assertEqual(result.state,'STRUCTURALLY_VALIDATED')
        self.assertEqual(result.missing_capabilities,('gml.pattern.lookup',))
    def test_binding_resolved(self):
        doc=parse((ROOT/'contracts/srai.gml').read_text())
        result=validate(doc,self.registry,self.bundle,{'gml.pattern.lookup':'string -> pattern_candidates'})
        self.assertEqual(result.state,'BINDINGS_VALIDATED')
    def test_bad_endpoint(self):
        doc=parse('graph [ schema "aiml-gml/1" node [ id 0 kind "category" ] edge [ source 0 target 9 verb "@has_pattern" ] ]')
        self.assertIn('V-local-resolves',validate(doc,self.registry).failures)
    def test_bad_template_ordinals(self):
        doc=parse('graph [ schema "aiml-gml/1" node [ id 1 kind "template" segment [ ordinal 2 kind "text" value "hi" ] ] ]')
        self.assertIn('V-template-ordinals: 1',validate(doc,self.registry).failures)
    def test_srai_requires_guard(self):
        doc=parse('graph [ schema "aiml-gml/1" node [ id 1 kind "srai" expression "X" max_depth 3 visited_guard 0 ] ]')
        self.assertIn('V-srai-safeguards-declared: 1',validate(doc,self.registry).failures)
    def test_mixed_endpoints(self):
        doc=parse('graph [ schema "aiml-gml/1" node [ id 0 kind "category" ] edge [ source 0 target_ref "aiml://patterns/main#1" verb "@has_pattern" ] ]')
        self.assertIn('V-endpoint-mode',validate(doc,self.registry,self.bundle).failures)
if __name__=='__main__': unittest.main()
