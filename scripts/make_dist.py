#!/usr/bin/env python3
"""build the zip that gets handed to somebody else.

what goes in is the app and its documentation, nothing else: no venv, no build
output, no tests, and none of the vendor artwork under `assets/`, which is other
people's files and not ours to redistribute.

the zip is reproducible - a fixed timestamp on every entry, entries in sorted
order - so building it twice from the same source gives the same bytes, and a
changed checksum means changed content.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# a fixed date, so the zip is a function of its contents alone. it is also the
# earliest a zip entry can carry: the format has no room for anything before it
EPOCH = (1980, 1, 1, 0, 0, 0)

# double-clicked, so they have to arrive executable. a zip carries unix modes in
# the high half of external_attr, and python does not set them for us
EXECUTABLE = ('ps2to3-importer.sh', 'ps2to3 importer.command')

# windows reads a .cmd line by line and a lone LF has bitten enough people
CRLF = ('ps2to3 importer.cmd',)

FILES = [
    'README.md',
    'LICENSE',
    'CONTRIBUTING.md',
    'pyproject.toml',
    'ps2to3-importer.sh',
    'ps2to3 importer.command',
    'ps2to3 importer.cmd',
    'ps2to3-importer.desktop',
    'docs/CHANGELOG.md',
]

TREES = [
    ('src/ps2to3', ('.py', '.json')),
    ('docs/decisions', ('.md',)),
]


def version():
    with open(os.path.join(ROOT, 'pyproject.toml'), encoding='utf-8') as fh:
        text = fh.read()
    found = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    if not found:
        raise SystemExit('no version in pyproject.toml')
    return found.group(1)


def collect():
    """(source path, path inside the zip) pairs, sorted, with nothing extra."""
    out = []
    for rel in FILES:
        out.append((os.path.join(ROOT, rel), rel))
    for tree, suffixes in TREES:
        base = os.path.join(ROOT, tree)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d != '__pycache__')
            for name in sorted(filenames):
                if name.endswith(suffixes):
                    src = os.path.join(dirpath, name)
                    out.append((src, os.path.relpath(src, ROOT)))
    missing = [rel for src, rel in out if not os.path.isfile(src)]
    if missing:
        raise SystemExit('ps2to3: not in the tree: ' + ', '.join(missing))
    return sorted(out, key=lambda pair: pair[1])


def build(out_path, prefix):
    entries = collect()
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)
    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for src, rel in entries:
            with open(src, 'rb') as fh:
                data = fh.read()
            if rel in CRLF:
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            info = zipfile.ZipInfo(f'{prefix}/{rel}', date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if rel in EXECUTABLE else 0o644
            info.external_attr = (0o100000 | mode) << 16
            z.writestr(info, data)
    return out_path, len(entries)


def main(argv=None):
    ap = argparse.ArgumentParser(description='build the distributable zip')
    ap.add_argument('-o', '--output', help='where to write it')
    args = ap.parse_args(argv)

    prefix = f'ps2to3-{version()}'
    out = args.output or os.path.join(ROOT, 'dist', prefix + '.zip')
    path, n = build(out, prefix)
    print(f'{path}  ({n} files, {os.path.getsize(path) / 1024:.0f} kB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
