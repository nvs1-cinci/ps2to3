"""comparing a conversion against the source it came from.

every text and custom-g-code option is re-read from the source, put through the
same value conversion, and compared with what was written. these are the values
whose corruption is least visible and most damaging.
"""

from __future__ import annotations

import os
import re

from .bundle import open_bundle
from .hardware import PrinterVariant
from .install import _sole_version_dir
from .values import Converter, Unset

TEXT_KEYS = ['start_gcode', 'end_gcode', 'before_layer_gcode', 'layer_gcode',
             'between_objects_gcode', 'color_change_gcode', 'pause_print_gcode',
             'template_custom_gcode', 'toolchange_gcode', 'start_filament_gcode',
             'end_filament_gcode', 'filament_notes', 'notes', 'printer_notes',
             'output_filename_format', 'filament_ramming_parameters']

# 2.x packs these as a vector of quoted items, four per substitution row, and no
# prusa 3.x preset sets either of them - so a conversion is the only thing that
# can get their shape wrong, and nothing else here would notice. the shape is
# right: 3.0.0-alpha10 read a converted `gcode_substitutions` back through
# `--save` as the same four-item row it was given.
VECTOR_KEYS = ['gcode_substitutions', 'post_process']

COMPARED_KEYS = TEXT_KEYS + VECTOR_KEYS


def _yaml_docs(path):
    """pyyaml is imported here, not at module scope.

    converting and installing are stdlib-only so the click-to-run launchers work
    without a pip install; only verify needs to read the yaml back.
    """
    import yaml
    with open(path, encoding='utf-8') as fh:
        return list(yaml.safe_load_all(fh))


def _yaml(path):
    import yaml
    with open(path, encoding='utf-8') as fh:
        return yaml.safe_load(fh)


def verify(ini, build, schema, vendor_id, keys=None):
    """Compare every text/G-code value in the 2.x source against the 3.x output."""
    # the reader's own G-code transformations have to be in effect, or its
    # intentional rewrites read as mismatches
    b = open_bundle(ini, valid_names={i['name'] for v in schema.raw.values()
                                      for i in v['items'] + v['overrides']},
                    fix_gcode=True, schema=schema)
    conv = Converter(schema, fix_gcode=True)
    vdir = _sole_version_dir(build, vendor_id)
    keys = keys or COMPARED_KEYS

    y_print, y_fil = {}, {}
    for f in sorted(os.listdir(vdir)):
        p = os.path.join(vdir, f)
        if f.startswith('preset-print-'):
            for d in _yaml_docs(p):
                if isinstance(d, dict) and d.get('name'):
                    y_print[d['name']] = d.get('values', {})
        elif f.startswith('preset-filament-'):
            for d in _yaml_docs(p):
                if isinstance(d, dict) and d.get('name'):
                    y_fil[d['name']] = d.get('values', {})
    y_printer = {}
    for f in sorted(os.listdir(vdir)):
        if not f.startswith('preset-printer-'):
            continue
        doc = _yaml(os.path.join(vdir, f))
        for var in doc.get('variants', []):
            m = re.search(r'printer\.model == "([^"]+)"', var.get('condition', ''))
            if not m:
                continue
            per_tool = {}
            for sub in var.get('variants', []):
                mm = re.search(r'nozzle_diameter == ([\d.]+)', sub.get('condition', ''))
                hf = 'and tool.nozzle_high_flow' in sub.get('condition', '')
                if mm:
                    per_tool[(float(mm.group(1)), hf)] = sub.get('values', {})
            y_printer[m.group(1)] = (var.get('values', {}), per_tool)

    checked = bad = 0
    problems = []
    # The converter keeps one 2.x printer preset per (model, nozzle, high-flow)
    # tool.  Bundles that describe an MMU or tool changer have several presets
    # per tool; the extra ones are not represented, so comparing against them
    # would report the surviving preset's values as mismatches.
    seen_tools = set()
    collapsed = []

    def cmp(label, key, raw, got, spec):
        nonlocal checked, bad
        if spec is None:
            return
        try:
            want = conv.coerce(key, raw, spec)
        except (ValueError, Unset):
            return
        if got is None:
            if str(want).strip():
                bad += 1
                problems.append(f'MISSING {label} :: {key}')
            return
        checked += 1
        if got != want:
            bad += 1
            problems.append(f'DIFFERS {label} :: {key}\n   2.x: {want!r}\n   3.x: {got!r}')

    for name in b.names('printer'):
        kv = b.resolve('printer', name)
        pv = PrinterVariant(name, kv)
        if pv.model not in y_printer:
            continue
        key = (pv.model, pv.tool)
        if key in seen_tools:
            collapsed.append(name)
            continue
        seen_tools.add(key)
        base, per_tool = y_printer[pv.model]
        eff = dict(base)
        eff.update(per_tool.get((pv.tool.nozzle, pv.tool.high_flow), {}))
        for k in keys:
            if k in kv:
                cmp(f'printer:{name}', k, kv[k], eff.get(k),
                    schema.by_kind['printer'].get(k))
    for name in b.names('print'):
        kv = b.resolve('print', name)
        if name not in y_print:
            continue
        for k in keys:
            if k in kv:
                cmp(f'print:{name}', k, kv[k], y_print[name].get(k),
                    schema.print_pool.get(k))
    for name in b.names('filament'):
        kv = b.resolve('filament', name)
        if name not in y_fil:
            continue
        for k in keys:
            if k in kv:
                cmp(f'filament:{name}', k, kv[k], y_fil[name].get(k),
                    schema.by_kind['filament'].get(k))
    return checked, bad, problems, collapsed
