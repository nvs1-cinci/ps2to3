"""reading and writing whole files.

every module here reads or writes a file in one shot, and each site was its own
bare `open(...)`, which leaves the handle to the garbage collector.

stdlib only, on purpose: converting and installing must work on a machine with a
plain python and no pip install (see the click-to-run launchers). pyyaml is only
needed to read a conversion back, which is `verify`.
"""

from __future__ import annotations

import json


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def write(path, text):
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


def read_json(path):
    # utf-8-sig: some vendor files (Snapmaker's, for one) start with a BOM
    with open(path, encoding='utf-8-sig') as fh:
        return json.load(fh)


def write_json(path, payload, **kw):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, **kw)
