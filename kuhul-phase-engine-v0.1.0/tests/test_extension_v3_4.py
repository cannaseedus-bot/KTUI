import sys,unittest
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from gml2 import parse
from extension import load_extension, ExtensionError
from registry import load_registry
from rules import _PREDICATES, RuleViolation
ROOT=Path(__file__).resolve().parents[1]
TEXT=(ROOT/'schemas/tensor-registry.gml').read_text()
class TestExtensionV34(unittest.TestCase):
    def test_tensor_extension_loads(self):
        ext=load_extension(parse(TEXT))
        self.assertEqual(ext.schema_id,'gml-tensor/1')
        self.assertEqual(ext.resolvers['gml'],'whole_graph')
        ext.require('dtype_match').check(source_dtype='float32',assembly_dtype='float32',source_id='x')
    def test_reject_unknown_authority(self):
        with self.assertRaisesRegex(ExtensionError,'authority'):
            load_extension(parse(TEXT.replace('authority "declaration_only"','authority "execute"',1)))
    def test_reject_arity_mismatch(self):
        with self.assertRaisesRegex(ExtensionError,'arity mismatch'):
            load_extension(parse(TEXT.replace('name "dtype_match" arity 3','name "dtype_match" arity 2')) )
    def test_reject_unregistered_predicate(self):
        with self.assertRaisesRegex(ExtensionError,'unknown predicate'):
            load_extension(parse(TEXT.replace('predicate "no_overlap"','predicate "not_registered"')) )
    def test_second_extension_cannot_inject_predicate(self):
        first=load_extension(parse(TEXT))
        second=TEXT.replace('schema_id "gml-tensor/1"','schema_id "aiml-gml/1"').replace('predicate "no_overlap"','predicate "evil_rule"')
        with self.assertRaises(ExtensionError): load_extension(parse(second))
        with self.assertRaisesRegex(RuleViolation,'dtype mismatch'):
            first.require('dtype_match').check(source_dtype='float32',assembly_dtype='float64',source_id='x')
    def test_table_immutable(self):
        with self.assertRaises(TypeError): _PREDICATES['evil_rule']=lambda:None
    def test_extension_constraints_immutable(self):
        ext=load_extension(parse(TEXT))
        with self.assertRaises(TypeError): ext.constraints['new']=None
    def test_bad_resolver_rejected(self):
        with self.assertRaisesRegex(ExtensionError,'resolver'):
            load_extension(parse(TEXT.replace('kind "whole_graph"','kind "node_addressable"')) )
    def test_registry_uses_extension(self):
        self.assertEqual(load_registry().extension.schema_id,'gml-tensor/1')
if __name__=='__main__':unittest.main()
