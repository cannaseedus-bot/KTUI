"""Closed, pure validation predicates selected by GML registry declarations.
No eval, imports from GML, execution dispatch, or mutation of caller state.
"""
import math
from registry import RegistryError

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

# Fixed trusted implementations. Never constructed from a registry expression.
_PREDICATES = {
    "data_count": data_count,
    "finite_values": finite_values,
    "dtype_match": dtype_match,
    "bounds_check": bounds_check,
    "no_overlap": no_overlap,
    "complete_coverage": complete_coverage,
}

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
