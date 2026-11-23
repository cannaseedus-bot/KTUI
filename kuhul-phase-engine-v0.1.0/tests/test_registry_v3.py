import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from gml2 import parse,serialize
from registry import load_registry,validate_document,RegistryError
from extension import owns_document
from assemble import load_directory
ROOT=Path(__file__).resolve().parents[1]
class TestRegistryV3(unittest.TestCase):
 def test_registry_validates_all_sources(self):
  """F14: the loader validates only documents this extension owns; a foreign one is refused."""
  docs=load_directory(ROOT/'contracts')
  reg=load_registry()
  owned=[doc for doc in docs.values() if owns_document(reg.extension,doc)]
  foreign=[doc for doc in docs.values() if not owns_document(reg.extension,doc)]
  self.assertTrue(owned,'fixtures must contain tensor documents')
  self.assertTrue(foreign,'fixtures must contain another extension, or the boundary is untested')
  for doc in owned: self.assertTrue(validate_document(doc,reg))
  with self.assertRaisesRegex(RegistryError,'schema mismatch'):
   validate_document(foreign[0],reg)
 def test_missing_shape_decl_fails_closed(self):
  text=(ROOT/'schemas/tensor-registry.gml').read_text()
  text='\n'.join(x for x in text.splitlines() if 'name "shape"' not in x)
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'registry.gml';p.write_text(text)
   with self.assertRaisesRegex(RegistryError,'missing field declarations'):load_registry(p)
 def test_unknown_tensor_field_rejected(self):
  doc=parse((ROOT/'contracts/col_a.gml').read_text().replace('rank 2','rank 2 extra 7'))
  with self.assertRaisesRegex(RegistryError,'unregistered field'):validate_document(doc,load_registry())
 def test_rank_declared_value_enforced(self):
  doc=parse((ROOT/'contracts/col_a.gml').read_text().replace('rank 2','rank 3'))
  with self.assertRaisesRegex(RegistryError,'required value'):validate_document(doc,load_registry())
 def test_unknown_shape_field_rejected(self):
  doc=parse((ROOT/'contracts/col_a.gml').read_text().replace('rows 4','rows 4 depth 2'))
  with self.assertRaisesRegex(RegistryError,'unregistered field'):validate_document(doc,load_registry())
if __name__=='__main__':unittest.main()
