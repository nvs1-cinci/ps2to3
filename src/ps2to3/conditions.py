"""evaluating a prusaslicer 2.x compatibility condition.

2.x expresses which printers a preset fits as an expression over the printer
preset's own options. the expression is transpiled to python and evaluated
against those values, which is what prusaslicer itself does, rather than
pattern-matching the handful of shapes vendors happen to write.
"""

from __future__ import annotations

import re


def _as_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Val:
    """A condition operand that compares across 2.x's loose value types.

    A 2.x .ini holds everything as text, and an option the preset never sets
    reads back as empty, so `min_layer_height > 0.1` can put a string next to a
    float.  Comparisons coerce instead of raising.
    """

    __slots__ = ('v',)

    def __init__(self, v):
        self.v = v

    def _pair(self, other):
        o = other.v if isinstance(other, Val) else other
        a = self.v
        if isinstance(a, str) and isinstance(o, (int, float)):
            n = _as_num(a)
            a = n if n is not None else 0.0
        elif isinstance(o, str) and isinstance(a, (int, float)):
            n = _as_num(o)
            o = n if n is not None else 0.0
        return a, o

    def __lt__(self, o):
        a, b = self._pair(o)
        return a < b

    def __le__(self, o):
        a, b = self._pair(o)
        return a <= b

    def __gt__(self, o):
        a, b = self._pair(o)
        return a > b

    def __ge__(self, o):
        a, b = self._pair(o)
        return a >= b

    def __eq__(self, o):
        a, b = self._pair(o)
        return a == b

    def __ne__(self, o):
        a, b = self._pair(o)
        return a != b

    def __hash__(self):
        return hash(self.v)

    def __bool__(self):
        if isinstance(self.v, str):
            return self.v not in ('', '0')
        return bool(self.v)

    def __str__(self):
        return str(self.v)


class ConditionEvaluator:
    """Evaluates a 2.x compatibility condition against a resolved preset.

    2.x conditions are a small expression language: and/or/!, parentheses,
    `key=~/regex/`, `key!~/regex/`, comparisons, and `key[0]` indexing.  Rather
    than pattern-matching the handful of shapes vendors happen to use, the
    expression is transpiled to Python and evaluated against the printer
    preset's own values - which is what PrusaSlicer itself does, and what makes
    tokens like `printer_notes=~/.*AFS.*/` work without special cases.
    """

    def __init__(self, values, missing=None):
        self.values = values
        self.missing = missing if missing is not None else set()

    def get(self, key, idx=None):
        raw = self.values.get(key)
        if raw is None:
            self.missing.add(key)
            return Val('')
        if idx is not None:
            parts = [p.strip() for p in raw.split(',')]
            raw = parts[idx] if idx < len(parts) else (parts[0] if parts else '')
        n = _as_num(raw)
        if n is not None:
            return Val(n)
        if raw in ('true', 'false'):
            return Val(raw == 'true')
        return Val(raw)

    @staticmethod
    def _truthy(v):
        return bool(v)

    def _match(self, value, pattern, negate=False):
        try:
            hit = re.search(pattern, str(value), re.S) is not None
        except re.error:
            raise ValueError(f'bad regex {pattern!r}') from None
        return (not hit) if negate else hit

    def transpile(self, expr):
        out, i, n = [], 0, len(expr)
        while i < n:
            c = expr[i]
            if c.isspace():
                out.append(c)
                i += 1
                continue
            if expr.startswith('&&', i):
                out.append(' and ')
                i += 2
                continue
            if expr.startswith('||', i):
                out.append(' or ')
                i += 2
                continue
            if expr.startswith('and', i) and not _ident_at(expr, i, 3):
                out.append(' and ')
                i += 3
                continue
            if expr.startswith('or', i) and not _ident_at(expr, i, 2):
                out.append(' or ')
                i += 2
                continue
            if c == '!' and not expr.startswith('!=', i) and not expr.startswith('!~', i):
                out.append(' not ')
                i += 1
                continue
            m = re.match(r'[A-Za-z_][A-Za-z_0-9]*', expr[i:])
            if m:
                key = m.group(0)
                i += len(key)
                idx = 'None'
                m2 = re.match(r'\s*\[\s*(\d+)\s*\]', expr[i:])
                if m2:
                    idx = m2.group(1)
                    i += m2.end()
                m3 = re.match(r'\s*(=~|!~)\s*/(.*?)(?<!\\)/', expr[i:], re.S)
                if m3:
                    i += m3.end()
                    neg = 'True' if m3.group(1) == '!~' else 'False'
                    out.append(f'_match(_get({key!r},{idx}), {m3.group(2)!r}, {neg})')
                    continue
                out.append(f'_get({key!r},{idx})')
                continue
            if expr.startswith('==', i) or expr.startswith('!=', i) or \
               expr.startswith('<=', i) or expr.startswith('>=', i):
                out.append(f' {expr[i:i+2]} ')
                i += 2
                continue
            if c in '<>()':
                out.append(c)
                i += 1
                continue
            m = re.match(r'\d+(\.\d+)?', expr[i:])
            if m:
                out.append(m.group(0))
                i += m.end()
                continue
            m = re.match(r'"([^"]*)"', expr[i:])
            if m:
                out.append(repr(m.group(1)))
                i += m.end()
                continue
            raise ValueError(f'cannot parse condition at {expr[i:i+30]!r}')
        return ''.join(out)

    def evaluate(self, expr):
        if not expr or not expr.strip():
            return True
        py = self.transpile(expr)
        env = {'_get': self.get, '_match': self._match,
               '__builtins__': {'True': True, 'False': False}}
        try:
            # the expression is transpiled from the .ini, not user-supplied code
            return self._truthy(eval(py, env))  # noqa: S307
        except TypeError as e:
            raise ValueError(f'{e} in {expr!r}') from None


def _ident_at(expr, i, ln):
    """True when expr[i:i+ln] is part of a longer identifier."""
    before = expr[i - 1] if i else ' '
    after = expr[i + ln] if i + ln < len(expr) else ' '
    def ident(ch):
        return ch.isalnum() or ch == '_'

    return ident(before) or ident(after)
