"""turning a 2.x option value into the 3.x one.

the schema decides the type, so a value is parsed the way 3.x will read it
rather than copied as text. anything that cannot be carried across is dropped
and reported, never guessed.
"""

from __future__ import annotations

import collections
import os

from .gcode import GCODE_OPTIONS, migrate_gcode

META_KEYS = {
    'inherits', 'renamed_from', 'compatible_printers', 'compatible_printers_condition',
    'compatible_prints_condition', 'print_settings_id', 'filament_settings_id',
    'printer_settings_id', 'sla_print_settings_id', 'sla_material_settings_id',
    'default_print_profile', 'default_filament_profile', 'default_sla_print_profile',
    'default_sla_material_profile',
    # hardware description that vendor.yaml now owns
    'printer_variant', 'nozzle_diameter', 'nozzle_high_flow', 'extruder_colour',
    # 2.x-only
    'support_material_auto', 'wipe_tower_x', 'wipe_tower_y', 'density',
    'filament_load_time', 'filament_unload_time',
}

# 3.x dropped the ability to express these as filament-level overrides under a
# `filament_` prefix; the un-prefixed option is overridable from a filament
# preset instead.
FILAMENT_PREFIX = 'filament_'


def parse_string_vector(raw):
    """Parse a 2.x vector-of-strings value.

    Items are ';'-separated and an item is double-quoted with C-style escapes
    when it contains ';', '"' or a newline - which is how 2.x stores
    start_filament_gcode, gcode_substitutions and friends.
    """
    if raw.strip() == '':
        return []
    out, i, n = [], 0, len(raw)
    while True:
        if i < n and raw[i] == '"':
            i += 1
            buf = []
            while i < n and raw[i] != '"':
                if raw[i] == '\\' and i + 1 < n:
                    nxt = raw[i + 1]
                    buf.append({'n': '\n', 'r': '\r', 't': '\t'}.get(nxt, nxt))
                    i += 2
                else:
                    buf.append(raw[i])
                    i += 1
            i += 1
            out.append(''.join(buf))
        else:
            j = raw.find(';', i)
            if j == -1:
                out.append(raw[i:])
                break
            out.append(raw[i:j])
            i = j
        if i < n and raw[i] == ';':
            i += 1
            if i == n:
                out.append('')
                break
            continue
        break
    return out


def unescape(v):
    out, i, n = [], 0, len(v)
    while i < n:
        if v[i] == '\\' and i + 1 < n:
            nxt = v[i + 1]
            if nxt in 'nrt':
                out.append({'n': '\n', 'r': '\r', 't': '\t'}[nxt])
                i += 2
                continue
            if nxt == '\\':
                out.append('\\')
                i += 2
                continue
        out.append(v[i])
        i += 1
    return ''.join(out)


def _num(v):
    v = v.strip()
    try:
        f = float(v)
    except ValueError:
        return None
    return int(f) if f.is_integer() and not any(c in v for c in '.eE') else f



class Unset(Exception):
    """A 2.x value that is empty, i.e. the option is simply not set."""


class Converter:
    """Converts 2.x values to 3.x, recording everything it could not carry."""

    def __init__(self, schema, fix_gcode=False):
        self.schema = schema
        self.fix_gcode = fix_gcode
        self.notes = collections.Counter()

    def note(self, msg):
        self.notes[msg] += 1

    def coerce(self, key, raw, spec):
        t = spec['type']
        if t == 'Bool':
            return raw.strip() in ('1', 'true', 'True')
        if t == 'Array':
            return self._array(key, raw, spec)
        if t in ('Int', 'OptInt', 'Float', 'Percentage', 'FloatOrPercentage'):
            raw = self._scalarise(key, raw)
            s = raw.strip()
            if s == '':
                raise Unset(key)
            if t in ('Percentage', 'FloatOrPercentage') and s.endswith('%'):
                return s
            n = _num(s)
            if n is None:
                raise ValueError(f'{key}: {s!r} is not a plain number '
                                 f'(3.x type is {t})')
            return int(n) if t in ('Int', 'OptInt') else n
        if t == 'Enum':
            v = self._scalarise(key, raw).strip()
            allowed = spec.get('enum_values', [])
            if v in allowed:
                return v
            mapped = self._bool_to_enum(key, v, allowed)
            if mapped is not None:
                self.note(f'{key}: 2.x boolean {v!r} read as {mapped!r} '
                          f'(3.x made this option an enum)')
                return mapped
            raise ValueError(f'{key}: {v!r} is not one of {allowed}')
        # String.  A leading quote means 2.x serialised a vector of strings.
        if raw.startswith('"'):
            items = parse_string_vector(raw)
            if len(items) > 1:
                self.note(f'{key}: 2.x held {len(items)} per-extruder values, kept the first')
            text = items[0] if items else ''
        else:
            text = unescape(raw)
        if key in GCODE_OPTIONS:
            text = migrate_gcode(text, self.note, self.fix_gcode)
        return text

    # Options that older 2.x bundles still store as 0/1 but 3.x models as an
    # enum.  The off/on pair is named explicitly rather than guessed, except for
    # the disabled/enabled fallback which is unambiguous.
    BOOL_ENUM = {
        'ensure_vertical_shell_thickness': ('disabled', 'enabled'),
        'draft_shield': ('disabled', 'enabled'),
        'gcode_label_objects': ('disabled', 'firmware'),
        'top_one_perimeter_type': ('none', 'top'),
        'fuzzy_skin': ('none', 'external'),
    }

    def _bool_to_enum(self, key, value, allowed):
        if value not in ('0', '1', 'false', 'true'):
            return None
        on = value in ('1', 'true')
        pair = self.BOOL_ENUM.get(key)
        if pair and pair[0] in allowed and pair[1] in allowed:
            return pair[1] if on else pair[0]
        if 'disabled' in allowed and 'enabled' in allowed:
            return 'enabled' if on else 'disabled'
        return None

    def _drop_stale_paths(self, kv):
        stale = {k: v for k, v in kv.items()
                 if k in self.PATH_KEYS and v.strip() and not os.path.isfile(v.strip())}
        if not stale:
            return kv
        kv = collections.OrderedDict(kv)
        for k, v in stale.items():
            kv[k] = ''
            self.note(f'{k} pointed at {v.strip()!r}, which does not exist here '
                      f'(an absolute path from the machine that exported the '
                      f'bundle); cleared, so the vendor bed model is used')
        return kv

    @staticmethod
    def _fix_thumbnails(kv):
        """Give every thumbnail size a format suffix.

        2.x kept the format in a separate `thumbnails_format` key, so a value can
        be a bare `300x300`
        3.x reads that as a 2-D vector and then refuses to
        store it in a string option.
        """
        raw = kv.get('thumbnails')
        if not raw or '/' in raw:
            return kv
        fmt = (kv.get('thumbnails_format') or 'PNG').strip().upper() or 'PNG'
        sizes = [x.strip() for x in raw.split(',') if x.strip()]
        kv = collections.OrderedDict(kv)
        kv['thumbnails'] = ', '.join(f'{x}/{fmt}' for x in sizes)
        return kv

    def _scalarise(self, key, raw):
        """Reduce a 2.x per-extruder vector to the scalar 3.x wants."""
        if ',' not in raw:
            return raw
        parts = [p.strip() for p in raw.split(',')]
        if len({p for p in parts}) > 1:
            self.note(f'{key}: 2.x had per-extruder values {raw!r}, kept the first '
                      f'({parts[0]!r}) - 3.x models this per tool preset')
        return parts[0]

    def _array(self, key, raw, spec):
        default = spec.get('value')
        if key == 'bed_shape' or (isinstance(default, list) and default
                                  and isinstance(default[0], list)):
            return [p.strip() for p in raw.split(',') if p.strip()]
        if isinstance(default, list) and default and isinstance(default[0], (int, float)):
            parts = [p.strip() for p in raw.split(',') if p.strip()]
            vals = [_num(p) if _num(p) is not None else p for p in parts]
            if not vals:
                return list(default)
            while len(vals) < len(default):        # 2.x omits the stealth-mode column
                vals.append(vals[-1])
            return vals[:len(default)]
        return parse_string_vector(raw)

    # A config bundle exported from the GUI records the custom bed as an absolute
    # path on the machine that exported it - `C:\Positron_bed.stl` - and 3.x is
    # unhappy loading a path that does not exist.  These override the vendor's
    # own bed model, so a stale one is worse than none.
    PATH_KEYS = ('bed_custom_model', 'bed_custom_texture')

    def values(self, kv, kind, extra_moves=None):
        """kv: resolved 2.x preset.  Returns the 3.x `values` mapping."""
        pool = self.schema.pool(kind)
        out = collections.OrderedDict()
        sm_auto = kv.get('support_material_auto', '1').strip()
        kv = self._fix_thumbnails(kv)
        kv = self._drop_stale_paths(kv)
        for k, raw in kv.items():
            if k in META_KEYS or raw.strip() == 'nil':
                continue
            key = k
            if kind == 'filament' and k.startswith(FILAMENT_PREFIX) and k not in pool:
                stripped = k[len(FILAMENT_PREFIX):]
                if stripped in pool:
                    key = stripped
            if key == 'support_material' and pool.get(key, {}).get('type') == 'Enum':
                out[key] = ('none' if raw.strip() in ('0', 'false')
                            else ('everywhere' if sm_auto == '1' else 'enforcers_only'))
                continue
            spec = pool.get(key)
            if spec is None:
                where = self.schema.where(key)
                self.note(f'{kind}: dropped {key} '
                          + (f'(3.x has it only on {"/".join(where)})' if where
                             else '(no 3.x equivalent)'))
                continue
            try:
                out[key] = self.coerce(key, raw, spec)
            except Unset:
                pass
            except ValueError as e:
                self.note(f'{kind}: dropped {e}')
        for k, raw in (extra_moves or {}).items():
            if k in out or raw.strip() == 'nil':
                continue
            spec = pool.get(k)
            if spec is None:
                continue
            try:
                out[k] = self.coerce(k, raw, spec)
            except Unset:
                pass
            except ValueError as e:
                self.note(f'{kind}: dropped moved {e}')
        return out
