"""Minimal GML bootstrap registry validation; no runtime dispatch."""
from pathlib import Path
from gml2 import parse, Block

class RegistryError(ValueError): pass

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
    required={('tensor','rank'),('tensor','shape'),('tensor.shape','rows'),('tensor.shape','cols'),('tensor','dtype'),('tensor','layout'),('slice','source_ref'),('slice','row_offset'),('slice','col_offset')}
    missing=required-set(fields)
    if missing: raise RegistryError(f'registry missing field declarations: {sorted(missing)}')
    if set(contracts)!={'tensor_source','tensor_assembly'}: raise RegistryError('incomplete contract registry')
    # Registry is load-bearing: unsupported field types fail at bootstrap.
    supported={'block','enum','integer','positive_integer','nonnegative_integer','graph_uri'}
    for (path,name),decl in fields.items():
        if one(decl,'type') not in supported:
            raise RegistryError(f'unsupported registry type: {path}.{name}')
    return contracts,fields

def validate_document(doc,registry):
    contracts,fields=registry
    if one(doc,'schema')!='gml-tensor/1': raise RegistryError('schema mismatch')
    contract=one(doc,'contract')
    if contract not in contracts: raise RegistryError('unregistered contract')
    for name in contracts[contract]:
        if not attrs(doc,name): raise RegistryError(f'missing required {name}')
    blocks=[('tensor',b) for b in attrs(doc,'tensor')]
    blocks += [('slice',b) for b in attrs(doc,'slice')]
    for path,b in blocks:
        if not isinstance(b,Block): raise RegistryError(f'{path} must be block')
        for (fpath,name),decl in fields.items():
            if fpath!=path: continue
            vals=attrs(b,name)
            if one(decl,'required',0)==1 and len(vals)!=1: raise RegistryError(f'{path}.{name} required once')
            if len(vals)>1: raise RegistryError(f'{path}.{name} duplicate')
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
                elif typ=='graph_uri' and (not isinstance(v,str) or not v.startswith('gml://')): raise RegistryError(f'{path}.{name} graph URI required')
        # Reject unregistered extension fields, rather than silently interpreting them.
        allowed={name for (fpath,name) in fields if fpath==path}
        for attr in b.entries:
            if attr.name not in allowed:
                raise RegistryError(f'unregistered field: {path}.{attr.name}')
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
