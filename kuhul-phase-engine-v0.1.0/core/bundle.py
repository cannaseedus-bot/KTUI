"""Read-only cross-file resolver for GML-owned AIML namespaces."""
from pathlib import Path
from gml2 import parse
from validate import one, attrs

def load_bundle(folder):
    bundle={}
    for path in Path(folder).glob('*.gml'):
        doc=parse(path.read_text(encoding='utf-8'))
        graph=one(doc,'graph_id')
        if not graph: raise ValueError(f'Missing graph_id in {path}')
        if graph.startswith('math/'):
            continue
        for node in attrs(doc,'node'):
            ref=f'aiml://{graph}#{one(node,"id")}'
            if ref in bundle: raise ValueError(f'Duplicate ref: {ref}')
            bundle[ref]=node
    return bundle
