"""translating orca's script dialect into prusaslicer's placeholder syntax.

both slicers evaluate `{...}` blocks over the same kind of expressions, and both
let a template declare local variables, so an orca macro is nearly a prusaslicer
one.  the two differences are structural:

| | orca | prusaslicer |
|---|---|---|
| a conditional | `if c then ... endif` | `{if c}` ... `{endif}` |
| emitting text | a string statement inside the block: `"G91\\n";` | text outside the braces |
| interpolating a value | `"G1 F" + speed + "\\n";` | `G1 F{speed}` |

so translation is: keep the expressions, take the text out of the block, and turn
the control flow inside out.  the target syntax is not guessed - it is what
prusaslicer's own CORE One INDX toolchange template is written in, including the
`T{next_extruder}` the template emits itself.

anything this module cannot translate confidently returns None, and the caller
drops the option: a half-translated macro that drives a tool head is worse than a
missing one.
"""

from __future__ import annotations

import re

KEYWORDS = frozenset(('if', 'then', 'elsif', 'else', 'endif', 'local', 'and',
                      'or', 'not', 'true', 'false'))

# functions the placeholder language provides, so not names to resolve
FUNCTIONS = frozenset(('min', 'max', 'int', 'round', 'digits', 'random', 'regex',
                       'empty', 'size', 'is_nil', 'interpolate_table', 'zhop'))

# a template that says nothing an expression could not say is left alone
SCRIPT_MARKERS = (re.compile(r'(?<![A-Za-z_0-9])then(?![A-Za-z_0-9])'),
                  re.compile(r'"\s*;'))


def looks_like_script(text):
    """True when `text` uses a construct prusaslicer's parser rejects."""
    return any(p.search(text) for p in SCRIPT_MARKERS)


class Unsupported(Exception):
    """the template uses something this module will not guess at."""


# --------------------------------------------------------------------------- #
# scanning
# --------------------------------------------------------------------------- #

def _skip_string(s, i):
    """index just past the string literal starting at s[i] == '"'."""
    i += 1
    while i < len(s):
        if s[i] == '\\':
            i += 2
            continue
        if s[i] == '"':
            return i + 1
        i += 1
    raise Unsupported('unterminated string literal')


def _word_at(s, i):
    m = re.compile(r'[A-Za-z_][A-Za-z_0-9]*').match(s, i)
    return m.group(0) if m else None


def _scan(s, i, stop_words):
    """Scan to the first stop word or `;` at depth 0, outside string literals.

    Returns (end index, the stop word found or ';').
    """
    depth = 0
    while i < len(s):
        c = s[i]
        if c == '"':
            i = _skip_string(s, i)
            continue
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif depth == 0:
            if c == ';':
                return i, ';'
            w = _word_at(s, i) if (c.isalpha() or c == '_') else None
            if w:
                if w in stop_words:
                    return i, w
                i += len(w)                  # never look inside an identifier
                continue
        i += 1
    raise Unsupported('statement does not end')


# --------------------------------------------------------------------------- #
# statements
# --------------------------------------------------------------------------- #

def _split_concat(expr):
    """Top-level `+` operands of an emit statement, strings kept as strings."""
    parts, start, depth, i = [], 0, 0, 0
    while i < len(expr):
        c = expr[i]
        if c == '"':
            i = _skip_string(expr, i)
            continue
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif c == '+' and depth == 0:
            parts.append(expr[start:i])
            start = i + 1
        i += 1
    parts.append(expr[start:])
    return [p.strip() for p in parts if p.strip()]


def _unquote(literal):
    body = literal[1:-1]
    out, i = [], 0
    while i < len(body):
        if body[i] == '\\' and i + 1 < len(body):
            nxt = body[i + 1]
            out.append({'n': '\n', 'r': '\r', 't': '\t'}.get(nxt, nxt))
            i += 2
            continue
        out.append(body[i])
        i += 1
    return ''.join(out)


def _as_text(part):
    """One operand of an emit statement, as text for outside the braces."""
    if part.startswith('"') and part.endswith('"') and len(part) >= 2:
        text = _unquote(part)
        if '{' in text or '}' in text:
            # a brace in emitted text would be read as a placeholder
            raise Unsupported('brace inside emitted text')
        return text
    return '{' + part + '}'


def _emit_statement(expr):
    return ''.join(_as_text(p) for p in _split_concat(expr))


def _assignment(expr, declare, locals_, note):
    """`x = e` / `x[i] = e`, which prusaslicer writes as its own block.

    Assigning to anything but a local the template declares is dropped: it is
    orca's own runtime state (`position[2] = position[2] + 2.0`), which
    prusaslicer does not have, and an unknown name makes it refuse the template.
    """
    lhs, _, rhs = expr.partition('=')
    if not rhs.strip() or not re.fullmatch(r'\s*[A-Za-z_][A-Za-z_0-9]*'
                                           r'(\s*\[[^\]]*\])?\s*', lhs):
        raise Unsupported(f'not an assignment: {expr[:40]!r}')
    name = re.match(r'\s*([A-Za-z_][A-Za-z_0-9]*)', lhs).group(1)
    if declare:
        locals_.add(name)
    elif name not in locals_:
        if note:
            note(f'custom G-code: dropped `{expr.strip()[:60]}`, which assigns to '
                 f'{name!r}, an orca runtime variable with no 3.x counterpart')
        return ''
    keyword = 'local ' if declare else ''
    return '{' + keyword + lhs.strip() + ' = ' + rhs.strip() + '}'


def _translate_statements(s, i, stop_words, out, locals_, note):
    """Translate statements until a stop word, appending to `out`."""
    while True:
        while i < len(s) and s[i] in ' \t\r\n':
            i += 1
        if i >= len(s):
            return i, None
        word = _word_at(s, i)
        if word in stop_words:
            return i + len(word), word

        if word == 'if':
            end, stop = _scan(s, i + 2, ('then',))
            if stop != 'then':
                raise Unsupported('if without then')
            out.append('{if ' + s[i + 2:end].strip() + '}')
            i = end + len('then')
            at_else = None
            while True:
                branch: list[str] = []
                i, stop = _translate_statements(
                    s, i, ('elsif', 'else', 'endif'), branch, locals_, note)
                out.extend(branch)
                if stop == 'endif':
                    if at_else is not None and len(out) == at_else:
                        out.pop()               # an else with nothing in it
                    out.append('{endif}')
                    break
                if stop == 'else':
                    out.append('{else}')
                    at_else = len(out)
                    continue
                if stop == 'elsif':
                    end, s2 = _scan(s, i, ('then',))
                    if s2 != 'then':
                        raise Unsupported('elsif without then')
                    out.append('{elsif ' + s[i:end].strip() + '}')
                    i = end + len('then')
                    continue
                raise Unsupported('if without endif')
            continue

        declare = word == 'local'
        start = i + len('local') if declare else i
        end, stop = _scan(s, start, ())
        if stop != ';':
            raise Unsupported('statement without ;')
        expr = s[start:end].strip()
        i = end + 1
        if not expr:
            continue
        if declare:
            out.append(_assignment(expr, True, locals_, note))
        elif re.match(r'\s*[A-Za-z_][A-Za-z_0-9]*(\s*\[[^\]]*\])?\s*=(?!=)', expr):
            out.append(_assignment(expr, False, locals_, note))
        else:
            out.append(_emit_statement(expr))


def _translate_block(body, locals_, note):
    out: list[str] = []
    _i, stop = _translate_statements(body, 0, (), out, locals_, note)
    if stop is not None:
        raise Unsupported(f'stray {stop!r}')
    return ''.join(out)


# --------------------------------------------------------------------------- #
# whole templates
# --------------------------------------------------------------------------- #

def _blocks(text):
    """(start, end) of each top-level `{...}` block, strings respected."""
    spans, i = [], 0
    while i < len(text):
        c = text[i]
        if c == '"':
            i = _skip_string(text, i)
            continue
        if c == '{':
            depth, j = 1, i + 1
            while j < len(text) and depth:
                if text[j] == '"':
                    j = _skip_string(text, j)
                    continue
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                j += 1
            if depth:
                raise Unsupported('unterminated block')
            spans.append((i, j))
            i = j
            continue
        i += 1
    return spans


def _unresolved(text, known, locals_):
    """Names a translated template still reads that 3.x would not know.

    The template is refused on any of them: an unknown variable makes 3.x reject
    the whole macro, which is the failure this module exists to avoid.
    """
    out = set()
    for start, end in _blocks(text):
        body = re.sub(r'"[^"]*"', ' ', text[start + 1:end - 1])
        for name in re.findall(r'[A-Za-z_][A-Za-z_0-9]*', body):
            if name in known or name in locals_ or name in KEYWORDS \
                    or name in FUNCTIONS:
                continue
            out.add(name)
    return out


def translate(text, known=frozenset(), note=None):
    """Orca script dialect -> prusaslicer placeholders, or None if not sure.

    Text outside a `{...}` block is already in prusaslicer's own form and is
    copied through untouched.  `known` is every name 3.x resolves (its options
    and its runtime placeholders); a translation that still reads something
    outside that is refused rather than shipped.
    """
    # locals are scoped to the whole template, and a block that needs no
    # translation still declares its own - so they are collected before any of it
    locals_: set[str] = set(re.findall(r'\blocal\s+([A-Za-z_][A-Za-z_0-9]*)', text))
    try:
        spans = _blocks(text)
        out, last = [], 0
        for start, end in spans:
            body = text[start + 1:end - 1]
            out.append(text[last:start])
            out.append(text[start:end] if not looks_like_script(body)
                       else _translate_block(body, locals_, note))
            last = end
        out.append(text[last:])
        got = ''.join(out)
    except (Unsupported, RecursionError):
        return None
    # the translation is only worth having if nothing scripty survived it
    if looks_like_script(got):
        return None
    if known and _unresolved(got, known, locals_):
        return None
    return got
