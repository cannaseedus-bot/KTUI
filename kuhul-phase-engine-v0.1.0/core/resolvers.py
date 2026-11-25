"""Scheme dispatch for whole-graph and node-addressable GML references."""
from pathlib import Path
import sys
from urllib.parse import urlsplit

_HOST_ROOT = Path(__file__).resolve().parents[2]
if str(_HOST_ROOT) not in sys.path:
    sys.path.insert(0, str(_HOST_ROOT))

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


def micronaut_column_resolver(ref, docs):
    """Resolve a typed GML Micronaut column; resolution is not dispatch or admission."""
    from gml_columns import resolve_column
    catalog = docs.get("__gml_operator_catalog__") if isinstance(docs, dict) else None
    return resolve_column(ref, catalog=catalog)

SCHEMES = {
    'gml': ('whole_graph', whole_graph_resolver),
    'aiml': ('node_addressable', node_in_graph_resolver),
    'micronaut': ('column_addressable', micronaut_column_resolver),
}

def resolve(ref, docs, expected=None, expected_schema=None):
    if not isinstance(ref,str) or '://' not in ref:
        raise ResolutionError(f'invalid reference: {ref!r}')
    scheme=ref.split('://',1)[0]
    if scheme not in SCHEMES: raise ResolutionError(f'unregistered URI scheme: {scheme!r}')
    mode, handler=SCHEMES[scheme]
    if expected is not None and expected != mode:
        raise ResolutionError(f'reference mode mismatch: expected {expected}, got {mode}')
    result = handler(ref,docs)
    if expected_schema is not None:
        if mode == 'column_addressable':
            schema = result.get('schema') if isinstance(result, dict) else None
            if schema != expected_schema:
                raise ResolutionError(f'reference schema mismatch: expected {expected_schema!r}, got {schema!r} for {ref!r}')
            return result
        u=urlsplit(ref)
        gid=u.netloc+u.path
        document=docs[gid]
        schemas=[a.value for a in document.entries if a.name=='schema']
        if len(schemas)!=1 or schemas[0]!=expected_schema:
            raise ResolutionError(f'reference schema mismatch: expected {expected_schema!r}, got {schemas!r} for {ref!r}')
    return result
