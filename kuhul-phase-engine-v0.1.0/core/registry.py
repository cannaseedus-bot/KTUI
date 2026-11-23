"""Minimal GML bootstrap registry validation; no runtime dispatch."""
from pathlib import Path
from dataclasses import dataclass
from gml2 import parse, Block
from extension import load_extension, ExtensionError

class RegistryError(ValueError): pass

@dataclass(frozen=True)
class Constraint:
    name: str
    predicate: str
    arity: int
    scope: str

    def check(self, **context):
        from rules import dispatch
        if len(context) != self.arity:
            raise RegistryError(f"constraint {self.name!r} expects {self.arity} arguments, got {len(context)}")
        return dispatch(self.predicate, **context)

@dataclass(frozen=True)
class Registry:
    contracts: dict
    fields: dict
    constraints: dict
    extension: object = None

    def require(self, name):
        rule = self.constraints.get(name)
        if rule is None:
            raise RegistryError(f"constraint {name!r} required but not declared in registry")
        return rule

    def __getitem__(self, index):
        return (self.contracts, self.fields, self.constraints)[index]

    def __iter__(self):
        return iter((self.contracts, self.fields, self.constraints))


def attrs(b,key): return [a.value for a in b.entries if a.name==key]
def one(b,key,default=None):
    v=attrs(b,key)
    if len(v)>1: raise RegistryError(f'duplicate {key}')
    return v[0] if v else default

def load_registry(path=None):
    if path is None: path=Path(__file__).resolve().parents[1]/'schemas/tensor-registry.gml'
    doc=parse(Path(path).read_text(encoding='utf8'))
    if one(doc,'schema')!='gml-registry/1': raise RegistryError('invalid registry bootstrap schema')
    ext=one(doc,'extension')
    if not isinstance(ext,Block) or one(ext,'schema_id')!='gml-tensor/1': raise RegistryError('invalid extension')
    contracts={}
    for c in attrs(doc,'contract'):
        name=one(c,'name')
        if not isinstance(name,str) or name in contracts: raise RegistryError('duplicate/invalid contract')
        contracts[name]=attrs(c,'required')
    fields={}
    for f in attrs(doc,'field'):
        path=one(f,'path'); name=one(f,'name'); typ=one(f,'type')
        if not all(isinstance(x,str) for x in (path,name,typ)): raise RegistryError('invalid field declaration')
        key=(path,name)
        if key in fields: raise RegistryError(f'duplicate field {key}')
        fields[key]=f
    required={('tensor','rank'),('tensor','shape'),('tensor.shape','rows'),('tensor.shape','cols'),('tensor','dtype'),('tensor','layout'),('slice','source_ref'),('slice','row_offset'),('slice','col_offset'),
          # M2: graph-level and data.value declarations are load-bearing too. Deleting one fails
          # here at bootstrap, not later as an "unregistered field" on every document.
          ('graph','schema'),('graph','graph_id'),('graph','contract'),('graph','tensor'),
          ('graph','data'),('graph','slice'),('graph','directed'),
          ('graph','coverage_policy'),('graph','overlap_policy'),('data','value')}
    missing=required-set(fields)
    if missing: raise RegistryError(f'registry missing field declarations: {sorted(missing)}')
    if set(contracts)!={'tensor_source','tensor_assembly'}: raise RegistryError('incomplete contract registry')
    # Registry is load-bearing: unsupported field types fail at bootstrap.
    supported={'block','enum','integer','positive_integer','nonnegative_integer','graph_uri','string','number'}
    for (path,name),decl in fields.items():
        if one(decl,'type') not in supported:
            raise RegistryError(f'unsupported registry type: {path}.{name}')
    for (path,name),decl in fields.items():
        repeatable=one(decl,'repeatable',0)
        if type(repeatable) is not int or repeatable not in (0,1):
            raise RegistryError(f'invalid repeatable declaration: {path}.{name}')
    required_rules={'data_count','finite_values','dtype_match','bounds_check','no_overlap','complete_coverage'}
    from rules import predicate_arity
    rules={}
    for rule in attrs(doc,'constraint'):
        name=one(rule,'name'); predicate=one(rule,'predicate'); scope=one(rule,'scope'); arity=one(rule,'arity')
        if name in rules or name not in required_rules or predicate!=name or scope not in ('source','assembly') or one(rule,'authority')!='declaration_only':
            raise RegistryError(f'invalid constraint declaration: {name}')
        if type(arity) is not int or arity < 0 or arity != predicate_arity(predicate):
            raise RegistryError(f"constraint {name!r} arity mismatch: declared {arity}, predicate expects {predicate_arity(predicate)}")
        rules[name]=Constraint(name,predicate,arity,scope)
    if set(rules)!=required_rules: raise RegistryError(f'missing constraint declarations: {sorted(required_rules-set(rules))}')
    try:
        extension=load_extension(doc)
    except ExtensionError as exc:
        raise RegistryError(str(exc)) from exc
    if extension.schema_id != "gml-tensor/1": raise RegistryError("tensor extension schema mismatch")
    if extension.resolvers.get("gml") != "whole_graph": raise RegistryError("tensor resolver not declared")
    return Registry(contracts,fields,rules,extension)

def validate_document(doc,registry):
    contracts,fields,*_=registry
    if one(doc,'schema') is None: raise RegistryError('document has no schema')
    if one(doc,'schema')!='gml-tensor/1': raise RegistryError('schema mismatch')
    contract=one(doc,'contract')
    if contract not in contracts: raise RegistryError('unregistered contract')
    for name in contracts[contract]:
        if not attrs(doc,name): raise RegistryError(f'missing required {name}')
    # M2: graph and data declarations are checked against the same registry.
    graph_allowed={name for (path,name) in fields if path=='graph'}
    for a in doc.entries:
        if a.name not in graph_allowed:
            raise RegistryError(f'unregistered field at graph level: graph.{a.name}')
    for name in graph_allowed:
        decl=fields[('graph',name)]
        vals=attrs(doc,name)
        if one(decl,'required',0)==1 and len(vals)!=1:
            raise RegistryError(f'graph.{name} required once')
        if len(vals)>1 and not (one(decl,'repeatable',0)==1 or name=='slice'):
            raise RegistryError(f'graph.{name} duplicate')
        for v in vals:
            typ=one(decl,'type')
            if typ=='enum' and v not in one(decl,'values','').split(','):
                raise RegistryError(f'graph.{name} enum mismatch')
            if typ=='block' and not isinstance(v,Block):
                raise RegistryError(f'graph.{name} must be block')
            if typ=='integer' and type(v)!=int:
                raise RegistryError(f'graph.{name} integer required')
            if typ=='string' and not isinstance(v,str):
                raise RegistryError(f'graph.{name} string required')
    blocks=[('data',b) for b in attrs(doc,'data')]
    blocks += [('tensor',b) for b in attrs(doc,'tensor')]
    blocks += [('slice',b) for b in attrs(doc,'slice')]
    for path,b in blocks:
        if not isinstance(b,Block): raise RegistryError(f'{path} must be block')
        for (fpath,name),decl in fields.items():
            if fpath!=path: continue
            vals=attrs(b,name)
            if one(decl,'required',0)==1 and len(vals)!=1: raise RegistryError(f'{path}.{name} required once')
            if len(vals)>1 and one(decl,'repeatable',0)!=1: raise RegistryError(f'{path}.{name} duplicate')
            for v in vals:
                exact=one(decl,'required_value')
                if exact is not None and v!=exact: raise RegistryError(f'{path}.{name} required value {exact}')
                typ=one(decl,'type')
                if typ=='block':
                    if not isinstance(v,Block): raise RegistryError(f'{path}.{name} must be block')
                    required_fields=one(decl,'required_fields','').split(',')
                    if any(len(attrs(v,k))!=1 for k in required_fields): raise RegistryError(f'{path}.{name} missing nested fields')
                elif typ=='enum':
                    if v not in one(decl,'values','').split(','): raise RegistryError(f'{path}.{name} enum mismatch')
                elif typ=='integer' and type(v)!=int: raise RegistryError(f'{path}.{name} integer required')
                elif typ=='positive_integer' and (type(v)!=int or v<=0): raise RegistryError(f'{path}.{name} positive integer required')
                elif typ=='nonnegative_integer' and (type(v)!=int or v<0): raise RegistryError(f'{path}.{name} nonnegative integer required')
                elif typ=='number' and (type(v) not in (int,float)):
                    raise RegistryError(f'{path}.{name} number required')
                elif typ=='graph_uri' and (not isinstance(v,str) or not v.startswith('gml://')): raise RegistryError(f'{path}.{name} graph URI required')
        # Reject unregistered extension fields, rather than silently interpreting them.
        allowed={name for (fpath,name) in fields if fpath==path}
        for attr in b.entries:
            if attr.name not in allowed:
                raise RegistryError(f'unregistered field in {path} block: {path}.{attr.name}')
        if path=='tensor':
            sh=one(b,'shape')
            if isinstance(sh,Block):
                nested={name:decl for (fpath,name),decl in fields.items() if fpath=='tensor.shape'}
                for attr in sh.entries:
                    if attr.name not in nested: raise RegistryError(f'unregistered field: tensor.shape.{attr.name}')
                for name,decl in nested.items():
                    v=one(sh,name)
                    if one(decl,'required',0)==1 and v is None: raise RegistryError(f'tensor.shape.{name} required')
                    if v is not None and (type(v)!=int or v<=0): raise RegistryError(f'tensor.shape.{name} positive integer required')
    return True
