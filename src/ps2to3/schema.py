"""the set of options prusaslicer 3.x accepts, and their types.

the schema is what makes the conversion type-aware rather than a text
substitution. prusaslicer can export it (`--export-config-schema`), and a copy
is shipped in the package so the tool works on a machine with no prusaslicer 3
installed to ask.
"""

from __future__ import annotations

import json
import os
import subprocess

from . import paths


class SchemaUnavailable(RuntimeError):
    """no schema shipped, cached, or obtainable from a local prusaslicer."""


class Schema:
    KINDS = ('printer', 'print', 'tool_print', 'filament',
             'sla_printer', 'sla_print', 'sla_material')

    def __init__(self, data):
        self.raw = data
        self.by_kind = {}
        for kind in self.KINDS:
            v = data.get(kind, {'items': [], 'overrides': []})
            self.by_kind[kind] = {i['name']: i for i in v['items'] + v['overrides']}
        # a print preset may carry Print-location options and their Tool overrides
        self.print_pool = dict(self.by_kind['tool_print'])
        self.print_pool.update(self.by_kind['print'])

    def pool(self, kind):
        return self.print_pool if kind == 'print' else self.by_kind[kind]

    def where(self, key):
        return [k for k in self.KINDS if key in self.by_kind[k]]

    def names(self):
        """every option name, across every preset kind."""
        return {name for kind in self.KINDS for name in self.by_kind[kind]}

    @classmethod
    def shipped_path(cls):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'schema.json')

    @classmethod
    def cached_path(cls):
        return os.path.join(paths.cache_dir(), 'schema.json')

    @classmethod
    def load(cls, path=None, datadir=None):
        """explicit path, then the cache, then the copy shipped in the package.

        only when none of those exist is prusaslicer asked for a fresh one.
        """
        # an asked-for schema that is not there is an error, not a reason to
        # convert against a different prusaslicer's vocabulary
        if path and not os.path.isfile(path):
            raise SchemaUnavailable(f'no schema at {path}')
        for cand in (path, cls.cached_path(), cls.shipped_path()):
            if cand and os.path.isfile(cand):
                return cls(json.load(open(cand, encoding='utf-8')))
        out = cls.cached_path()
        export_schema(out, datadir=datadir)
        return cls(json.load(open(out, encoding='utf-8')))


def export_schema(out_path, command=None, datadir=None):
    """ask a locally installed prusaslicer 3 for its config schema."""
    command = command or paths.slicer_command()
    if not command:
        raise SchemaUnavailable(
            'prusaslicer 3 was not found on this machine, so its option schema '
            f'cannot be exported. set {paths.ENV_SLICER} to the executable, or '
            'pass a schema file')
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    cmd = list(command) + ['--export-config-schema', out_path]
    if datadir:
        cmd += ['--datadir', datadir]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        raise SchemaUnavailable(f'{" ".join(command)} could not be run: {e}') from None
    if not os.path.isfile(out_path):
        raise SchemaUnavailable(
            f'{" ".join(command)} did not write a schema to {out_path}')
    return out_path
