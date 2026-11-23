"""GML/2 tensor assembly: declarative validation and optional pure materialization.
No kernel dispatch, XCFE admission, or implicit micronaut lookup.
"""
from dataclasses import dataclass
from pathlib import Path
import math
import sys
from typing import Mapping
from gml2 import Block, parse
from resolvers import resolve, ResolutionError
from registry import load_registry, validate_document
from rules import RuleViolation

class AssemblyError(ValueError): pass

def values(block, key):
    return [a.value for a in block.entries if a.name == key]

def field(block, key, default=None):
    vals = values(block, key)
    if len(vals)>1: raise AssemblyError(f'duplicate singleton field {key}')
    return vals[0] if vals else default

def integer(v, name, minimum=0):
    if type(v) is not int or v < minimum: raise AssemblyError(f'{name}: expected integer >= {minimum}')
    return v

def shape_of(b):
    s=field(b,'shape')
    if not isinstance(s,Block): raise AssemblyError('shape block required')
    rows=integer(field(s,'rows'),'rows',1); cols=integer(field(s,'cols'),'cols',1)
    return (rows,cols)

@dataclass(frozen=True)
class Slice:
    ref: str
    offset: tuple[int,int]
    shape: tuple[int,int]
    values: tuple[float,...] | None

@dataclass(frozen=True)
class Plan:
    graph_id: str
    shape: tuple[int,int]
    dtype: str
    slices: tuple[Slice,...]
    coverage: int
    total: int
    state: str = 'STRUCTURALLY_VALIDATED'

def graph_identity(doc):
    gid=field(doc,'graph_id')
    if not isinstance(gid,str) or not gid: raise AssemblyError('graph_id required')
    return gid

def parse_source(doc, registry=None):
    registry=registry or load_registry()
    validate_document(doc,registry)
    if field(doc,'schema')!='gml-tensor/1' or field(doc,'contract')!='tensor_source':
        raise AssemblyError('source must declare gml-tensor/1 tensor_source')
    gid=graph_identity(doc)
    t=field(doc,'tensor')
    if not isinstance(t,Block): raise AssemblyError('tensor declaration missing')
    # rank is enforced by the registry
    shape=shape_of(t)
    dtype=field(t,'dtype')
    # dtype enum is enforced by the registry
    # layout enum is enforced by the registry
    data=field(doc,'data')
    vals=None
    if data is not None:
        if not isinstance(data,Block): raise AssemblyError('data must be block')
        raw=values(data,'value')
        registry.require('data_count').check(values=raw,shape=shape)
        registry.require('finite_values').check(values=raw)
        vals=tuple(float(x) for x in raw)
    return shape,dtype,vals

def resolve_ref(ref, docs):
    try:
        return resolve(ref, docs, expected="whole_graph", expected_schema="gml-tensor/1")
    except ResolutionError as exc:
        raise AssemblyError(str(exc)) from exc

def assemble(doc, docs: Mapping[str,Block], materialize=False):
    if field(doc,'schema')!='gml-tensor/1' or field(doc,'contract')!='tensor_assembly':
        raise AssemblyError('assembly must declare gml-tensor/1 tensor_assembly')
    registry=load_registry()
    validate_document(doc,registry)
    for required in ("data_count","finite_values","dtype_match","bounds_check","no_overlap","complete_coverage"):
        registry.require(required)
        registry.extension.require(required)
    gid=graph_identity(doc)
    t=field(doc,'tensor')
    if not isinstance(t,Block): raise AssemblyError('tensor block required')
    shape=shape_of(t); dtype=field(t,'dtype')
    # dtype/layout/rank are registry-validated
    if field(doc,'overlap_policy','reject')!='reject': raise AssemblyError('only reject overlap supported')
    if field(doc,'coverage_policy','complete') not in ('complete','sparse'):
        raise AssemblyError('invalid coverage_policy')
    # Validate every supplied source before assembling, even when callers bypass load_directory.
    source_cache = {}
    for source_id, source_doc in docs.items():
        if field(source_doc,'contract') == 'tensor_source':
            source_cache[source_id] = parse_source(source_doc,registry)
    # Resolve and preflight all slices before allocating or writing output.
    prepared=[]
    for block in values(doc,'slice'):
        if not isinstance(block,Block): raise AssemblyError('slice must be block')
        ref=field(block,'source_ref'); src=resolve_ref(ref,docs)
        src_id=graph_identity(src)
        if src_id not in source_cache: raise AssemblyError(f'not a tensor_source: {ref!r}')
        src_shape,src_dtype,src_data=source_cache[src_id]
        registry.require('dtype_match').check(source_dtype=src_dtype,assembly_dtype=dtype,source_id=src_id)
        row=integer(field(block,'row_offset'),'row_offset'); col=integer(field(block,'col_offset'),'col_offset')
        registry.require('bounds_check').check(row=row,col=col,source_shape=src_shape,target_shape=shape)
        prepared.append((ref,row,col,src_shape,src_data))
    if materialize:
        missing=sorted({ref for ref,_,_,_,data in prepared if data is None})
        if missing: raise AssemblyError('cannot materialize unbound source data: '+', '.join(missing))
    occupied=set(); slices=[]; out=[None]*(shape[0]*shape[1]) if materialize else None
    for ref,row,col,src_shape,src_data in prepared:
        for r in range(src_shape[0]):
            for c in range(src_shape[1]):
                dst=(row+r,col+c)
                registry.require('no_overlap').check(destination=dst,occupied=occupied)
                occupied.add(dst)
                if materialize: out[dst[0]*shape[1]+dst[1]]=src_data[r*src_shape[1]+c]
        slices.append(Slice(ref,(row,col),src_shape,src_data))
    total=shape[0]*shape[1]
    registry.require('complete_coverage').check(coverage_policy=field(doc,'coverage_policy','complete'),occupied=occupied,total=total)
    return Plan(gid,shape,dtype,tuple(slices),len(occupied),total), (tuple(out) if materialize else None)

def load_directory(path, registry_path=None):
    docs={}
    for f in sorted(Path(path).glob('*.gml')):
        doc=parse(f.read_text(encoding='utf-8'))
        gid=graph_identity(doc)
        if gid in docs: raise AssemblyError(f'duplicate graph_id: {gid}')
        docs[gid]=doc
    registry = load_registry(registry_path)
    for gid, doc in docs.items():
        from extension import owns_document
        if not owns_document(registry.extension, doc):
            continue
        validate_document(doc, registry)
        if field(doc,'contract') == 'tensor_source':
            parse_source(doc,registry)
    return docs

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('directory'); p.add_argument('graph_id'); p.add_argument('--materialize',action='store_true')
    args=p.parse_args(); docs=load_directory(args.directory)
    plan,data=assemble(docs[args.graph_id],docs,args.materialize)
    print(f'{plan.state}: {plan.graph_id} shape={plan.shape} coverage={plan.coverage}/{plan.total}')
    if data is not None:
        for r in range(plan.shape[0]): print(data[r*plan.shape[1]:(r+1)*plan.shape[1]])
