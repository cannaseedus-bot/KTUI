import sys, unittest, tempfile
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"core"))
from registry import load_registry, RegistryError
from rules import check, RuleViolation
from assemble import assemble, load_directory
ROOT=Path(__file__).resolve().parents[1]

class TestV33(unittest.TestCase):
    def setUp(self):
        self.docs=load_directory(ROOT/'contracts')
        self.registry=load_registry()

    def altered(self,old,new):
        content=(ROOT/'schemas/tensor-registry.gml').read_text().replace(old,new)
        d=tempfile.TemporaryDirectory()
        path=Path(d.name)/'registry.gml';path.write_text(content)
        return d,path

    def test_require_dispatch(self):
        self.registry.require('dtype_match').check(source_dtype='float32',assembly_dtype='float32',source_id='a')
        with self.assertRaisesRegex(RuleViolation,'dtype mismatch'):
            self.registry.require('dtype_match').check(source_dtype='float32',assembly_dtype='float64',source_id='a')

    def test_missing_required_rule_callsite(self):
        self.registry.constraints.pop('no_overlap')
        with patch('assemble.load_registry',return_value=self.registry):
            with self.assertRaisesRegex(RegistryError,'required but not declared'):
                assemble(self.docs['tensor/assembled'],self.docs)

    def test_wrong_arity_registry_rejected(self):
        d,p=self.altered('name "dtype_match" arity 3','name "dtype_match" arity 2')
        with d:
            with self.assertRaisesRegex(RegistryError,'arity mismatch'): load_registry(p)

    def test_missing_arity_registry_rejected(self):
        d,p=self.altered('name "dtype_match" arity 3','name "dtype_match"')
        with d:
            with self.assertRaisesRegex(RegistryError,'arity mismatch'): load_registry(p)

    def test_bad_context_arity_rejected(self):
        with self.assertRaisesRegex(RegistryError,'expects 3 arguments'):
            self.registry.require('dtype_match').check(source_dtype='float32')

    def test_unknown_predicate_registry_rejected(self):
        d,p=self.altered('predicate "no_overlap"','predicate "unsafe"')
        with d:
            with self.assertRaises(RegistryError):load_registry(p)

    def test_all_six_callsite_require(self):
        for name in ('data_count','finite_values','dtype_match','bounds_check','no_overlap','complete_coverage'):
            self.assertEqual(self.registry.require(name).name,name)

if __name__=='__main__':unittest.main()
