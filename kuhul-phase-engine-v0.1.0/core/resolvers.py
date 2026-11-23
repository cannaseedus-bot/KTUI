"""Scheme dispatch for whole-graph and node-addressable GML references."""
from urllib.parse import urlsplit

class ResolutionError(ValueError): pass

def whole_graph_resolver(ref, docs):
    u=urlsplit(ref)
    if u.fragment or u.query or not u.netloc or not u.path.strip('/'):
        raise ResolutionError(f'invalid whole-graph reference: {ref!r}')
    gid=u.netloc+u.path
    if gid not in docs: raise ResolutionError(f'unresolved graph: {ref!r}')
    return docs[gid]

def node_in_graph_resolver(ref, docs):
    u=urlsplit(ref)
    if not u.netloc or not u.path.strip('/') or not u.fragment.isdecimal() or u.query:
        raise ResolutionError(f'invalid node reference: {ref!r}')
    gid=u.netloc+u.path
    if gid not in docs: raise ResolutionError(f'unresolved graph: {ref!r}')
    from gml2 import Block
    nodes=[a.value for a in docs[gid].entries if a.name=='node' and isinstance(a.value,Block)]
    hits=[n for n in nodes if any(a.name=='id' and a.value==int(u.fragment) for a in n.entries)]
    if len(hits)!=1: raise ResolutionError(f'unresolved node: {ref!r}')
    return hits[0]

SCHEMES = {
    'gml': ('whole_graph', whole_graph_resolver),
    'aiml': ('node_addressable', node_in_graph_resolver),
}

def resolve(ref, docs, expected=None):
    if not isinstance(ref,str) or '://' not in ref:
        raise ResolutionError(f'invalid reference: {ref!r}')
    scheme=ref.split('://',1)[0]
    if scheme not in SCHEMES: raise ResolutionError(f'unregistered URI scheme: {scheme!r}')
    mode, handler=SCHEMES[scheme]
    if expected is not None and expected != mode:
        raise ResolutionError(f'reference mode mismatch: expected {expected}, got {mode}')
    return handler(ref,docs)
