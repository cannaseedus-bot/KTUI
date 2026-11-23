import sys,unittest
from pathlib import Path
from dataclasses import replace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'core'))
from gml2 import parse,serialize,Block,Attribute
from extension import load_extension,ExtensionError
from aiml_bundle import Bundle
from rules import RuleViolation
from registry import load_registry
from assemble import load_directory,assemble
REG=(ROOT/'schemas/aiml-registry.gml').read_text()
def fixture():
    return {f'{p.stem}/main':parse(p.read_text()) for p in (ROOT/'aiml_contracts').glob('*.gml')}
def bundle(reg=REG,docs=None): return Bundle(fixture() if docs is None else docs,load_extension(parse(reg)))
class TestAIMLPort(unittest.TestCase):
    def test_valid_bundle(self): self.assertEqual(bundle().validate(),'BINDINGS_VALIDATED')
    def test_missing_constraint_preflight(self):
        text=REG.replace(' constraint [ name "template_ordinals" predicate "template_ordinals_contiguous" arity 1 scope "node" authority "declaration_only" ]','')
        with self.assertRaisesRegex(ExtensionError,'template_ordinals'): bundle(text)
    def test_dynamic_static_redirect_rejected(self):
        docs=fixture();docs['srai/main']=Block(docs['srai/main'].entries+(Attribute("edge",parse('graph [ edge [ source 4 target 4 verb "@redirects_to" ] ]').entries[0].value),))
        with self.assertRaisesRegex(RuleViolation,'dynamic SRAI'): bundle(docs=docs).validate()
    def test_capture_out_of_range(self):
        docs=fixture();docs['template/main']=parse(serialize(docs['template/main']).replace('index 1','index 3'))
        with self.assertRaisesRegex(RuleViolation,'capture out of range'): bundle(docs=docs).validate()
    def test_mixed_endpoints(self):
        docs=fixture();docs['category/main']=Block(docs['category/main'].entries+(Attribute("edge",parse('graph [ edge [ source 3 target_ref "aiml://pattern/main#1" ] ]').entries[0].value),))
        with self.assertRaisesRegex(RuleViolation,'endpoint'): bundle(docs=docs).validate()
    def test_two_domains_coexist(self):
        self.assertEqual(bundle().validate(),'BINDINGS_VALIDATED')
        docs=load_directory(ROOT/'contracts');plan,data=assemble(docs['tensor/assembled'],docs,materialize=True)
        self.assertEqual(plan.coverage,12);self.assertEqual(len(data),12)
    def test_arity_rejected(self):
        with self.assertRaisesRegex(ExtensionError,'arity mismatch'): bundle(REG.replace('predicate "wildcard_count_matches" arity 2','predicate "wildcard_count_matches" arity 1'))
    def test_unknown_authority(self):
        with self.assertRaisesRegex(ExtensionError,'authority'): bundle(REG.replace('authority "declaration_only"','authority "execute"',1))
    def test_bad_node_reference(self):
        docs=fixture();docs['category/main']=parse(serialize(docs['category/main']).replace('pattern/main#1','pattern/main#99'))
        with self.assertRaisesRegex(ValueError,'unresolved node'): bundle(docs=docs).validate()
    def test_contract_mismatch(self):
        docs=fixture();docs['category/main']=parse(serialize(docs['category/main']).replace('aiml://pattern/main#1','aiml://template/main#1'))
        with self.assertRaisesRegex(ValueError,'unresolved node'): bundle(docs=docs).validate()
if __name__=='__main__':unittest.main()
