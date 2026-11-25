"""GML/2 portable-subset parser and canonical serializer. No execution semantics."""
from dataclasses import dataclass
import re

@dataclass(frozen=True)
class Attribute:
    name: str
    value: object

@dataclass(frozen=True)
class Block:
    entries: tuple[Attribute, ...]

class GMLSyntaxError(ValueError):
    pass

_TOKEN = re.compile(r'''\s+|\(\*.*?\*\)|"(?:\\.|[^"\\])*"|[\[\]]|[+-]?(?:\d+\.\d*(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?)|[A-Za-z_][A-Za-z0-9_]*''', re.S)
_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
_NUM = re.compile(r'[+-]?(?:\d+\.\d*(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?)\Z')

def tokenize(src):
    pos = 0
    out = []
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m:
            raise GMLSyntaxError(f'Unexpected character at offset {pos}: {src[pos:pos+24]!r}')
        token = m.group()
        pos = m.end()
        if not token.isspace() and not token.startswith('(*'):
            out.append(token)
    return out

def decode_string(token):
    result = []
    i = 1
    while i < len(token)-1:
        c = token[i]
        if c == '\\':
            i += 1
            if i >= len(token)-1:
                raise GMLSyntaxError('Incomplete string escape')
            e = token[i]
            result.append({'n':'\n','t':'\t','"':'"','\\':'\\'}.get(e, '\\'+e))
        else:
            result.append(c)
        i += 1
    return ''.join(result)

def parse(src):
    tokens = tokenize(src)
    p = 0
    def take(expected=None):
        nonlocal p
        if p >= len(tokens):
            raise GMLSyntaxError(f'Unexpected end; expected {expected or "token"}')
        t = tokens[p]
        if expected is not None and t != expected:
            raise GMLSyntaxError(f'Expected {expected!r} at token {p}, got {t!r}')
        p += 1
        return t
    def block():
        nonlocal p
        take('[')
        attrs = []
        while p < len(tokens) and tokens[p] != ']':
            name = take()
            if not _IDENT.fullmatch(name):
                raise GMLSyntaxError(f'Expected attribute identifier, got {name!r}')
            token = take()
            if token == '[':
                # The opening bracket was consumed: rewind for recursive parse.
                p -= 1
                val = block()
            elif token.startswith('"'):
                val = decode_string(token)
            elif _NUM.fullmatch(token):
                val = float(token) if '.' in token or 'e' in token.lower() else int(token)
            else:
                raise GMLSyntaxError(f'Expected value after {name!r}, got {token!r}')
            attrs.append(Attribute(name, val))
        take(']')
        return Block(tuple(attrs))
    take('graph')
    result = block()
    if p != len(tokens):
        raise GMLSyntaxError('Trailing tokens after graph')
    return result

def quote(value):
    return '"' + value.replace('\\','\\\\').replace('"','\\"').replace('\n','\\n').replace('\t','\\t') + '"'

def serialize(doc):
    if not isinstance(doc, Block):
        raise TypeError('Expected Block')
    def emit(block, depth):
        lines = []
        for attr in block.entries:
            if not _IDENT.fullmatch(attr.name):
                raise ValueError(f'Invalid identifier {attr.name!r}')
            prefix = '  ' * depth + attr.name + ' '
            v = attr.value
            if isinstance(v, Block):
                lines.append(prefix + '[')
                lines.extend(emit(v, depth+1))
                lines.append('  '*depth + ']')
            elif isinstance(v, str):
                lines.append(prefix + quote(v))
            elif isinstance(v, int) and not isinstance(v, bool):
                lines.append(prefix + str(v))
            elif isinstance(v, float):
                if not __import__('math').isfinite(v):
                    raise ValueError('Nonfinite number')
                lines.append(prefix + repr(v))
            else:
                raise TypeError(f'Unsupported GML value: {type(v)}')
        return lines
    return 'graph [\n' + '\n'.join(emit(doc, 1)) + '\n]\n'
