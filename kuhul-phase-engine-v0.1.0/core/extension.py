"""GML/2 shared extension contract. GML selects trusted rules; never defines code."""
from dataclasses import dataclass
from typing import Mapping
from types import MappingProxyType
from gml2 import Block
from rules import predicate_arity, dispatch

class ExtensionError(ValueError): pass

def values(block, name):
    return [a.value for a in block.entries if a.name == name]

def one(block, name, default=None):
    found=values(block,name)
    if len(found)>1: raise ExtensionError(f"duplicate {name}")
    return found[0] if found else default

@dataclass(frozen=True)
class Constraint:
    name: str
    predicate: str
    arity: int
    scope: str
    authority: str
    def check(self, **context):
        if len(context)!=self.arity:
            raise ExtensionError(f"constraint {self.name!r} expects {self.arity} arguments, got {len(context)}")
        return dispatch(self.predicate, **context)

@dataclass(frozen=True)
class Extension:
    schema_id: str
    constraints: Mapping[str, Constraint]
    resolvers: Mapping[str, str]
    owner: str = ''
    def __post_init__(self):
        if not isinstance(self.schema_id,str) or not self.schema_id:
            raise ExtensionError('invalid extension schema_id')
        for name,rule in self.constraints.items():
            if name!=rule.name: raise ExtensionError(f'{self.schema_id}: constraint key mismatch')
            if rule.authority!='declaration_only':
                raise ExtensionError(f'{self.schema_id}: constraint {name!r} unknown authority {rule.authority!r}')
            if rule.scope not in ('source','assembly','bundle','node'):
                raise ExtensionError(f'{self.schema_id}: invalid scope {rule.scope!r}')
            try: actual=predicate_arity(rule.predicate)
            except ValueError as exc: raise ExtensionError(f'{self.schema_id}: {exc}') from exc
            if type(rule.arity) is not int or rule.arity!=actual:
                raise ExtensionError(f'{self.schema_id}: constraint {name!r} arity mismatch: {rule.arity} vs {actual}')
        from resolvers import SCHEMES
        for scheme,kind in self.resolvers.items():
            if scheme not in SCHEMES or SCHEMES[scheme][0]!=kind:
                raise ExtensionError(f'{self.schema_id}: unregistered or incompatible resolver {scheme!r}')
        object.__setattr__(self,'constraints',MappingProxyType(dict(self.constraints)))
        object.__setattr__(self,'resolvers',MappingProxyType(dict(self.resolvers)))
    def require(self,name):
        rule=self.constraints.get(name)
        if rule is None: raise ExtensionError(f'{self.schema_id}: constraint {name!r} required but not declared')
        return rule

def load_extension(doc):
    if one(doc,'schema')!='gml-registry/1': raise ExtensionError('invalid registry bootstrap schema')
    extension=one(doc,'extension')
    if not isinstance(extension,Block): raise ExtensionError('missing extension block')
    schema_id=one(extension,'schema_id'); owner=one(extension,'owner','')
    constraints={}; resolvers={}
    for block in values(doc,'constraint'):
        if not isinstance(block,Block): raise ExtensionError('invalid constraint block')
        name=one(block,'name')
        if not isinstance(name,str) or name in constraints: raise ExtensionError(f'{schema_id}: duplicate/invalid constraint {name!r}')
        constraints[name]=Constraint(name,one(block,'predicate'),one(block,'arity'),one(block,'scope'),one(block,'authority'))
    for block in values(doc,'resolver'):
        scheme=one(block,'scheme');kind=one(block,'kind')
        if not isinstance(scheme,str) or scheme in resolvers: raise ExtensionError(f'{schema_id}: duplicate/invalid resolver')
        resolvers[scheme]=kind
    return Extension(schema_id,constraints,resolvers,owner)


def owns_document(extension, doc):
    """Schema ownership gate: other extensions are not ours to validate."""
    schema = one(doc, 'schema')
    if schema is None:
        raise ExtensionError('document has no schema')
    return schema == extension.schema_id
