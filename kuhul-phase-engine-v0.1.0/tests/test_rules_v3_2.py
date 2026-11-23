import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from gml2 import parse,serialize
from registry import load_registry,RegistryError
from assemble import load_directory,assemble
from rules import check,RuleViolation
ROOT=Path(__file__).resolve().parents[1]
class TestRuleDispatch(unittest.TestCase):
 def setUp(self):
  self.docs=load_directory(ROOT/'contracts')
  self.root=self.docs['tensor/assembled']
 def test_float64_materializes_when_matched(self):
  docs={k:parse(serialize(v).replace('dtype "float32"','dtype "float64"')) for k,v in self.docs.items()}
  plan,data=assemble(docs['tensor/assembled'],docs,True)
  self.assertEqual(plan.dtype,'float64');self.assertEqual(len(data),12)
 def test_dtype_mismatch_public_path(self):
  root=parse(serialize(self.root).replace('dtype "float32"','dtype "float64"'))
  with self.assertRaisesRegex(RuleViolation,'dtype mismatch: assembly float64, source tensor/col_a float32'):
   assemble(root,{**self.docs,'tensor/assembled':root})
 def test_constraint_deletion_fails_closed(self):
  s=(ROOT/'schemas/tensor-registry.gml').read_text()
  s='\n'.join(x for x in s.splitlines() if 'name "no_overlap"' not in x)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'registry.gml';p.write_text(s)
   with self.assertRaisesRegex(RegistryError,'missing constraint declarations'):load_registry(p)
 def test_unknown_predicate_fails(self):
  s=(ROOT/'schemas/tensor-registry.gml').read_text().replace('predicate "no_overlap"','predicate "arbitrary_code"')
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'registry.gml';p.write_text(s)
   with self.assertRaisesRegex(RegistryError,'invalid constraint'):load_registry(p)
 def test_rule_dispatch_overlap(self):
  with self.assertRaisesRegex(RuleViolation,'overlap'):
   check(load_registry(),'no_overlap',destination=(0,0),occupied={(0,0)})
 def test_registry_declares_all_six_rules(self):
  self.assertEqual(set(load_registry()[2]),{'data_count','finite_values','dtype_match','bounds_check','no_overlap','complete_coverage'})
if __name__=='__main__':unittest.main()
