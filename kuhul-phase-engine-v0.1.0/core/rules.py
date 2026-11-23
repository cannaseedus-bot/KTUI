"""Closed, pure validation predicates selected by GML registry declarations.
No eval, imports from GML, execution dispatch, or mutation of caller state.
"""
import math
class RegistryError(ValueError): pass
from types import MappingProxyType

class RuleViolation(ValueError): pass

def data_count(*, values, shape):
    if len(values)!=shape[0]*shape[1]: raise RuleViolation('data count does not match shape')

def finite_values(*, values):
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in values):
        raise RuleViolation('data must be finite numbers')

def dtype_match(*, source_dtype, assembly_dtype, source_id):
    if source_dtype!=assembly_dtype:
        raise RuleViolation(f'dtype mismatch: assembly {assembly_dtype}, source {source_id} {source_dtype}')

def bounds_check(*, row, col, source_shape, target_shape):
    if row+source_shape[0]>target_shape[0] or col+source_shape[1]>target_shape[1]:
        raise RuleViolation('slice out of bounds')

def no_overlap(*, destination, occupied):
    if destination in occupied: raise RuleViolation(f'overlap at {destination}')

def complete_coverage(*, coverage_policy, occupied, total):
    if coverage_policy=='complete' and len(occupied)!=total:
        raise RuleViolation(f'incomplete coverage: {len(occupied)}/{total}')

# AIML predicates are trusted built-ins registered before any extension is loaded.
def wildcard_count_matches(*, expression, wildcard_count):
    if type(wildcard_count) is not int or wildcard_count < 0 or expression.count('*') != wildcard_count:
        raise RuleViolation('pattern wildcard_count mismatch')

def srai_static_ok(*, node):
    if '{star:' in _one(node,'expression',''):
        raise RuleViolation('dynamic SRAI cannot use static @redirects_to')

def srai_guards_present(*, node):
    depth=_one(node,'max_depth'); guard=_one(node,'visited_guard')
    if type(depth) is not int or depth < 1 or guard != 1:
        raise RuleViolation('SRAI requires positive max_depth and visited_guard 1')

def template_ordinals_contiguous(*, node):
    segments=_many(node,'segment'); ordinals=[_one(seg,'ordinal') for seg in segments]
    if any(type(i) is not int for i in ordinals) or sorted(ordinals)!=list(range(len(ordinals))):
        raise RuleViolation('template segment ordinals not contiguous')

def template_capture_in_range(*, node, wildcard_count):
    for seg in _many(node,'segment'):
        if _one(seg,'kind')=='capture':
            i=_one(seg,'index')
            if type(i) is not int or not 1<=i<=wildcard_count:
                raise RuleViolation('template capture out of range')

def endpoint_modes_consistent(*, bundle):
    for doc in bundle.graphs.values():
        for edge in _many(doc,'edge'):
            local=(_one(edge,'source') is not None,_one(edge,'target') is not None)
            external=(_one(edge,'source_ref') is not None,_one(edge,'target_ref') is not None)
            if (all(local) and not any(external)) or (all(external) and not any(local)):
                continue
            raise RuleViolation('mixed or incomplete edge endpoint mode')

def _many(block, name):
    from gml2 import Block
    return [a.value for a in block.entries if a.name==name and isinstance(a.value,Block)]

def _one(block,name,default=None):
    found=[a.value for a in block.entries if a.name==name]
    if len(found)>1: raise RuleViolation('duplicate '+name)
    return found[0] if found else default

# Fixed trusted implementations. Never constructed from a registry expression.
_PREDICATES = MappingProxyType({
    "data_count": data_count,
    "finite_values": finite_values,
    "dtype_match": dtype_match,
    "bounds_check": bounds_check,
    "no_overlap": no_overlap,
    "complete_coverage": complete_coverage,
    "wildcard_count_matches": wildcard_count_matches,
    "srai_static_ok": srai_static_ok,
    "srai_guards_present": srai_guards_present,
    "template_ordinals_contiguous": template_ordinals_contiguous,
    "template_capture_in_range": template_capture_in_range,
    "endpoint_modes_consistent": endpoint_modes_consistent,
})

def predicate_arity(name):
    """Number of keyword-only inputs accepted by a trusted predicate."""
    import inspect
    fn = _PREDICATES.get(name)
    if fn is None:
        raise RegistryError(f"unknown predicate: {name!r}")
    params = inspect.signature(fn).parameters.values()
    if any(p.kind != inspect.Parameter.KEYWORD_ONLY for p in params):
        raise RegistryError(f"predicate has unsupported signature: {name!r}")
    return len(inspect.signature(fn).parameters)

def dispatch(predicate, **context):
    fn = _PREDICATES.get(predicate)
    if fn is None:
        raise RegistryError(f"unregistered predicate: {predicate!r}")
    if len(context) != predicate_arity(predicate):
        raise RegistryError(f"predicate {predicate!r} expects {predicate_arity(predicate)} arguments, got {len(context)}")
    return fn(**context)

def check(registry, name, **context):
    """Compatibility facade; every invocation requires a declared rule."""
    return registry.require(name).check(**context)


def freeze():
    """Predicate dispatch is backed by an immutable mapping from import time."""
    return True
