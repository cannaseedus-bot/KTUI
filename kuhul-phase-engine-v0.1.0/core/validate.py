"""GML-owned micronaut contract validator; no execution or implicit dispatch."""
from dataclasses import dataclass
from gml2 import Block, parse

@dataclass(frozen=True)
class Result:
    state: str
    failures: tuple
    missing_capabilities: tuple = ()

def attrs(b, key):
    return [a.value for a in b.entries if a.name == key]

def one(b, key, default=None):
    v=attrs(b,key)
    return v[0] if v else default

def validate(doc, registry, bundle=None, capabilities=None):
    errors=[]
    schema=one(doc,'schema')
    definitions={one(s,'schema_id'):s for s in attrs(registry,'node') if isinstance(s,Block)}
    spec=definitions.get(schema)
    if not spec: return Result('REJECTED',(f'V-schema: unknown {schema}',))
    graph_id=one(doc,'graph_id')
    nodes=attrs(doc,'node'); edges=attrs(doc,'edge')
    ids={}
    kinds={}
    for n in nodes:
        nid=one(n,'id'); kind=one(n,'kind')
        if type(nid) is not int or nid < 0 or nid in ids: errors.append(f'V-ids: {nid}')
        else: ids[nid]=n; kinds[nid]=kind
        if not isinstance(kind,str): errors.append(f'V-kind: node {nid}')
        if kind=='srai':
            depth=one(n,'max_depth'); guard=one(n,'visited_guard')
            if type(depth) is not int or depth<1 or guard!=1: errors.append(f'V-srai-safeguards-declared: {nid}')
            budget=one(doc,'redirect_budget',3)
            if type(depth) is int and depth>budget: errors.append(f'V-srai-depth-bounded: {nid}')
        if kind=='template':
            seg=attrs(n,'segment'); ords=[one(s,'ordinal') for s in seg]
            if ords!=list(range(len(seg))): errors.append(f'V-template-ordinals: {nid}')
            for s in seg:
                if one(s,'kind') not in ('text','capture','srai','conditional','random','call'):
                    errors.append(f'V-template-segment-kinds: {nid}')
                if one(s,'kind')=='capture' and (type(one(s,'index')) is not int or one(s,'index')<1):
                    errors.append(f'V-template-capture-index: {nid}')
    for e in edges:
        local=attrs(e,'source') or attrs(e,'target')
        external=attrs(e,'source_ref') or attrs(e,'target_ref')
        if bool(local)==bool(external): errors.append('V-endpoint-mode'); continue
        if local:
            s=one(e,'source'); t=one(e,'target')
            if type(s) is not int or type(t) is not int or s not in ids or t not in ids: errors.append('V-local-resolves')
            src=ids.get(s)
        else:
            refs=[one(e,'source_ref'),one(e,'target_ref')]
            if any(not isinstance(r,str) or not r.startswith('aiml://') or '#' not in r for r in refs): errors.append('V-external-ref-format')
            if bundle is not None and any(r not in bundle for r in refs): errors.append('V-external-resolves')
            src=bundle.get(refs[0]) if bundle else None
        if one(e,'verb')=='@redirects_to' and src is not None and one(src,'kind')=='srai' and '{star:' in one(src,'expression',''):
            errors.append('V-srai-static-only-if-literal')
    if errors: return Result('REJECTED',tuple(errors))
    if capabilities is None: return Result('STRUCTURALLY_VALIDATED',())
    required=set()
    for n in nodes:
        for r in attrs(n,'requires'):
            cap=one(r,'capability'); sig=one(r,'signature')
            if not isinstance(cap,str) or not isinstance(sig,str): return Result('REJECTED',('V-requires-shape',))
            required.add((cap,sig))
    missing=tuple(sorted(cap for cap,sig in required if capabilities.get(cap)!=sig))
    if missing: return Result('STRUCTURALLY_VALIDATED',(),missing)
    return Result('BINDINGS_VALIDATED',())
