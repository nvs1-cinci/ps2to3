"""rendering values as the yaml prusaslicer 3.x reads."""

from __future__ import annotations

import base64
import hashlib
import re


def yscalar(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v)
    if s == '':
        return "''"
    return "'" + s.replace("'", "''") + "'"


def yflow(v):
    if isinstance(v, list):
        return '[' + ', '.join(yscalar(x) for x in v) + ']'
    return yscalar(v)


def _needs_quoting(text):
    """Block scalars cannot round-trip trailing whitespace, tabs-as-indent, or a
    value that is nothing but newlines (which would read back as empty)."""
    if text.strip() == '':
        return True
    return any(ln != ln.rstrip() for ln in text.split('\n')) or '\t' in text


def _dq(text):
    esc = (text.replace('\\', '\\\\').replace('"', '\\"')
               .replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t'))
    return '"' + esc + '"'


def yvalues(mapping, indent):
    """Render a `values:` mapping, preserving multi-line strings exactly."""
    pad = ' ' * indent
    lines = []
    for k, v in mapping.items():
        if isinstance(v, str) and '\n' in v:
            if _needs_quoting(v):
                lines.append(f'{pad}{k}: {_dq(v)}')
                continue
            # chomping indicator chosen so the trailing newlines survive
            trailing = len(v) - len(v.rstrip('\n'))
            style = '|-' if trailing == 0 else ('|' if trailing == 1 else '|+')
            body = v.rstrip('\n') if trailing else v
            lines.append(f'{pad}{k}: {style}')
            for ln in body.split('\n'):
                lines.append(f'{pad}  {ln}' if ln else '')
            for _ in range(max(0, trailing - 1)):
                lines.append('')
        else:
            lines.append(f'{pad}{k}: {yflow(v)}')
    return lines


def mkid(seed):
    """Deterministic base64-encoded UUIDv4.

    3.x parses preset ids as UUIDs; every id in Prusa's own bundle is a v4 with
    the RFC-4122 variant bits, and ids that are merely 22 random base64 chars
    are silently rejected.
    """
    b = bytearray(hashlib.sha256(seed.encode()).digest()[:16])
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    return base64.b64encode(bytes(b)).decode().rstrip('=')


def slug(s):
    return re.sub(r'[^A-Za-z0-9]+', '-', s).strip('-')
