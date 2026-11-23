"""Read-only AIML/GML six-contract validation; no template evaluation."""
from dataclasses import dataclass
from gml2 import Block
from extension import ExtensionError
from resolvers import resolve, ResolutionError
from rules import RuleViolation

CONTRACTS=('pattern','template','category','srai','retrieval','composition')
RULES=('pattern_wildcard_count','srai_static_only_if_literal','srai_safeguards_declared','template_ordinals','template_capture_bounds','endpoint_mode')

def many(block,name): return [a.value for a in block.entries if a.name==name]
def one(block,name,default=None):
    found=many(block,name)
    if len(found)>1: raise ValueError(f'duplicate {name}')
    return found[0] if found else default

@dataclass(frozen=True)
class Bundle:
    graphs: dict
    extension: object
    def __post_init__(self):
        if self.extension.schema_id!='aiml-gml/1': raise ExtensionError('wrong AIML extension')
        if self.extension.resolvers.get('aiml')!='node_addressable': raise ExtensionError('AIML resolver required')
        object.__setattr__(self,'rules',{n:self.extension.require(n) for n in RULES})
        found=set()
        for gid,doc in self.graphs.items():
            if one(doc,'schema')!='aiml-gml/1' or one(doc,'graph_id')!=gid: raise ValueError('invalid AIML graph identity')
            contract=one(doc,'contract')
            if contract not in CONTRACTS or contract in found: raise ValueError('duplicate/invalid AIML contract')
            found.add(contract)
            ids=[one(n,'id') for n in many(doc,'node')]
            if any(type(i) is not int or i<0 for i in ids) or len(ids)!=len(set(ids)):
                raise ValueError('duplicate/invalid node id')
        if found!=set(CONTRACTS): raise ValueError('missing AIML contracts: '+str(sorted(set(CONTRACTS)-found)))
    def nodes(self,kind):
        return [(gid,n) for gid,d in self.graphs.items() for n in many(d,'node') if one(n,'kind')==kind]
    def validate(self):
        self.rules['endpoint_mode'].check(bundle=self)
        for gid,doc in self.graphs.items():
            ids={one(n,'id') for n in many(doc,'node')}
            for edge in many(doc,'edge'):
                if one(edge,'source_ref') is not None:
                    for key in ('source_ref','target_ref'):
                        ref=one(edge,key)
                        node=resolve(ref,self.graphs,expected='node_addressable',expected_schema='aiml-gml/1')
                        contract=ref.split('://',1)[1].split('/',1)[0]
                        target_gid=ref.split('://',1)[1].split('#',1)[0]
                        if one(self.graphs[target_gid],'contract')!=contract: raise ValueError('AIML URI contract mismatch')
                else:
                    if one(edge,'source') not in ids or one(edge,'target') not in ids:
                        raise ValueError('unresolved local endpoint')
        for _,node in self.nodes('pattern'):
            self.rules['pattern_wildcard_count'].check(expression=one(node,'expression'),wildcard_count=one(node,'wildcard_count'))
        for gid,node in self.nodes('srai'):
            self.rules['srai_safeguards_declared'].check(node=node)
            if any(one(e,'verb')=='@redirects_to' and (one(e,'source')==one(node,'id') or one(e,'source_ref')==f'aiml://{gid}#{one(node,"id")}') for e in many(self.graphs[gid],'edge')):
                self.rules['srai_static_only_if_literal'].check(node=node)
        for _,node in self.nodes('template'):
            self.rules['template_ordinals'].check(node=node)
        # Category joins resolve pattern and template nodes before capture validation.
        for _,cat in self.nodes('category'):
            pattern=resolve(one(cat,'pattern_ref'),self.graphs,expected='node_addressable',expected_schema='aiml-gml/1')
            template=resolve(one(cat,'template_ref'),self.graphs,expected='node_addressable',expected_schema='aiml-gml/1')
            if one(pattern,'kind')!='pattern' or one(template,'kind')!='template': raise ValueError('invalid category bindings')
            self.rules['template_capture_bounds'].check(node=template,wildcard_count=one(pattern,'wildcard_count'))
        return 'BINDINGS_VALIDATED'
