import sys,unittest,re,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from gml2 import parse,serialize
from assemble import assemble,load_directory,AssemblyError
from registry import RegistryError,load_registry
from rules import RuleViolation
P=Path(__file__).resolve().parents[1]/'contracts'
class TestAssembly(unittest.TestCase):
    def setUp(self):
        self.docs=load_directory(P)
        self.root=self.docs['tensor/assembled']
    def test_unused_malformed_source(self):
        with tempfile.TemporaryDirectory() as d:
            for f in P.glob('*.gml'): (Path(d)/f.name).write_text(f.read_text())
            (Path(d)/'unused.gml').write_text('graph [ schema "gml-tensor/1" contract "tensor_source" graph_id "tensor/unused" tensor [ rank 2 shape [ rows 2 cols 2 ] dtype "float32" layout "row_major" ] data [ value 1.0 ] ]')
            with self.assertRaisesRegex(RuleViolation,'data count'): load_directory(d)
    def test_materialize_unbound_source(self):
        docs=dict(self.docs)
        source=docs['tensor/col_a']
        from gml2 import Block
        docs['tensor/col_a']=Block(tuple(a for a in source.entries if a.name!='data'))
        with self.assertRaisesRegex(AssemblyError,'gml://tensor/col_a'): assemble(self.root,docs,True)
    def test_unsupported_dtype(self):
        x=serialize(self.root).replace('dtype "float32"','dtype "float16"')
        with self.assertRaisesRegex(RegistryError,'tensor.dtype enum mismatch'): assemble(parse(x),self.docs)
    def test_dtype_mismatch(self):
        root=parse(serialize(self.root).replace('dtype "float32"','dtype "float64"'))
        with self.assertRaisesRegex(RuleViolation,'dtype mismatch'):
            assemble(root,{**self.docs,'tensor/assembled':root})
    def test_registry_field_removed_fails_closed(self):
        registry=(Path(__file__).resolve().parents[1]/'schemas/tensor-registry.gml').read_text()
        registry=registry.replace('  field [ path "tensor" name "layout" type "enum" values "row_major" required 1 ]\n','')
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'registry.gml';f.write_text(registry)
            with self.assertRaisesRegex(RegistryError,'missing field declarations'): load_registry(f)
    def test_duplicate_graph_id(self):
        with tempfile.TemporaryDirectory() as d:
            for f in P.glob('*.gml'): (Path(d)/f.name).write_text(f.read_text())
            (Path(d)/'duplicate.gml').write_text((P/'col_a.gml').read_text())
            with self.assertRaisesRegex(AssemblyError,'duplicate graph_id'): load_directory(d)
    def test_roundtrip(self):
        for doc in self.docs.values(): self.assertEqual(parse(serialize(doc)),doc)
    def test_matrix(self):
        plan,data=assemble(self.root,self.docs,True)
        self.assertEqual(plan.shape,(6,2))
        self.assertEqual(data,(1.,5.,2.,6.,3.,7.,4.,8.,9.,10.,11.,12.))
    def test_plan_only(self):
        plan,data=assemble(self.root,self.docs)
        self.assertEqual(plan.coverage,12); self.assertIsNone(data)
    def test_overlap(self):
        x=serialize(self.root).replace('row_offset 4\n    col_offset 0','row_offset 0\n    col_offset 0')
        with self.assertRaisesRegex(RuleViolation,'overlap'): assemble(parse(x),self.docs)
    def test_bounds(self):
        x=serialize(self.root).replace('row_offset 4\n    col_offset 0','row_offset 5\n    col_offset 0')
        with self.assertRaisesRegex(RuleViolation,'out of bounds'): assemble(parse(x),self.docs)
    def test_missing(self):
        x=serialize(self.root).replace('gml://tensor/col_a','gml://tensor/absent')
        with self.assertRaisesRegex(AssemblyError,'unresolved'): assemble(parse(x),self.docs)
    def test_gap(self):
        x=serialize(self.root).replace('row_offset 4\n    col_offset 0','row_offset 3\n    col_offset 0')
        with self.assertRaises(RuleViolation): assemble(parse(x),self.docs)
    def test_bad_shape(self):
        x=serialize(self.docs['tensor/col_a']).replace('rows 4\n      cols 1','rows 3\n      cols 1')
        docs=dict(self.docs);docs['tensor/col_a']=parse(x)
        with self.assertRaisesRegex(RuleViolation,'data count'): assemble(self.root,docs)
    def test_sparse(self):
        x=serialize(self.root).replace('coverage_policy "complete"','coverage_policy "sparse"').replace('row_offset 4\n    col_offset 0','row_offset 3\n    col_offset 0')
        with self.assertRaisesRegex(RuleViolation,'overlap'): assemble(parse(x),self.docs)
    def test_rank(self):
        x=serialize(self.root).replace('rank 2','rank 3')
        with self.assertRaisesRegex(RegistryError,'tensor.rank required value 2'): assemble(parse(x),self.docs)
if __name__=='__main__': unittest.main()
