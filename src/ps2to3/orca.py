#!/usr/bin/env python3
"""orca/bambu json profile reader.

OrcaSlicer (and BambuStudio, which it forked from, and forks of Orca such as
Snapmaker's) store profiles as a tree of JSON files instead of PrusaSlicer's
single INI, and renamed most of the option vocabulary along the way.  This module
presents such a tree with the same interface as `ps2to3.Bundle`, translating
Orca's names back to PrusaSlicer 2.x ones - after which the existing 2.x -> 3.x
pipeline does the rest.

The mapping was not guessed.  Orca ships profiles for the same Prusa machines
that PrusaSlicer 2.x ships, so each Orca preset was aligned to its 2.x
counterpart (by agreement on the ~115 option names both formats already share)
and the renames read off the pairs whose *values* agree.  That is where the
non-obvious ones come from - `overhang_1_4_speed` is PrusaSlicer's
`overhang_speed_3`, not `_0`, with 14/14 agreement across aligned pairs.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re

from . import files, orca_script
from .bundle import SourceError

# --------------------------------------------------------------------------- #
# key renames: Orca -> PrusaSlicer 2.x
# --------------------------------------------------------------------------- #

MACHINE_RENAMES = {
    'printable_area': 'bed_shape',
    'printable_height': 'max_print_height',
    'machine_start_gcode': 'start_gcode',
    'machine_end_gcode': 'end_gcode',
    'before_layer_change_gcode': 'before_layer_gcode',
    'layer_change_gcode': 'layer_gcode',
    'change_filament_gcode': 'toolchange_gcode',
    'machine_pause_gcode': 'pause_print_gcode',
    'retraction_length': 'retract_length',
    'retraction_speed': 'retract_speed',
    'deretraction_speed': 'deretract_speed',
    'detraction_speed': 'deretract_speed',        # misspelt in shipped profiles
    'retraction_minimum_travel': 'retract_before_travel',
    'retract_when_changing_layer': 'retract_layer_change',
    'z_hop': 'retract_lift',
    'machine_max_speed_x': 'machine_max_feedrate_x',
    'machine_max_speed_y': 'machine_max_feedrate_y',
    'machine_max_speed_z': 'machine_max_feedrate_z',
    'machine_max_speed_e': 'machine_max_feedrate_e',
    'extruder_clearance_height_to_rod': 'extruder_clearance_height',
    'machine_tool_change_time': 'filament_change_time',
}

PROCESS_RENAMES = {
    # walls and shells
    'wall_loops': 'perimeters',
    'wall_generator': 'perimeter_generator',
    'top_shell_layers': 'top_solid_layers',
    'bottom_shell_layers': 'bottom_solid_layers',
    'top_shell_thickness': 'top_solid_min_thickness',
    'bottom_shell_thickness': 'bottom_solid_min_thickness',
    'detect_thin_wall': 'thin_walls',
    'detect_overhang_wall': 'overhangs',
    'only_one_wall_first_layer': 'only_one_perimeter_first_layer',
    # layers and widths
    'initial_layer_print_height': 'first_layer_height',
    'inital_layer_height': 'first_layer_height',  # misspelt in shipped profiles
    'line_width': 'extrusion_width',
    'initial_layer_line_width': 'first_layer_extrusion_width',
    'outer_wall_line_width': 'external_perimeter_extrusion_width',
    'inner_wall_line_width': 'perimeter_extrusion_width',
    'sparse_infill_line_width': 'infill_extrusion_width',
    'internal_solid_infill_line_width': 'solid_infill_extrusion_width',
    'top_surface_line_width': 'top_infill_extrusion_width',
    'support_line_width': 'support_material_extrusion_width',
    # infill
    'sparse_infill_density': 'fill_density',
    'sparse_infill_pattern': 'fill_pattern',
    'top_surface_pattern': 'top_fill_pattern',
    'bottom_surface_pattern': 'bottom_fill_pattern',
    'infill_direction': 'fill_angle',
    'infill_wall_overlap': 'infill_overlap',
    'minimum_sparse_infill_area': 'solid_infill_below_area',
    # speed
    'outer_wall_speed': 'external_perimeter_speed',
    'inner_wall_speed': 'perimeter_speed',
    'sparse_infill_speed': 'infill_speed',
    'internal_solid_infill_speed': 'solid_infill_speed',
    'top_surface_speed': 'top_solid_infill_speed',
    'gap_infill_speed': 'gap_fill_speed',
    'support_speed': 'support_material_speed',
    'support_interface_speed': 'support_material_interface_speed',
    'initial_layer_speed': 'first_layer_speed',
    'initial_layer_infill_speed': 'first_layer_solid_infill_speed',
    'enable_overhang_speed': 'enable_dynamic_overhang_speeds',
    # Orca counts overhang in quarters of *supported* width, PrusaSlicer in
    # quarters of unsupported - so the four speeds run in opposite order.
    # 14/14 agreement on aligned Prusa profiles for both ends of the range.
    'overhang_1_4_speed': 'overhang_speed_3',
    'overhang_2_4_speed': 'overhang_speed_2',
    'overhang_3_4_speed': 'overhang_speed_1',
    'overhang_4_4_speed': 'overhang_speed_0',
    # acceleration
    'outer_wall_acceleration': 'external_perimeter_acceleration',
    'inner_wall_acceleration': 'perimeter_acceleration',
    'sparse_infill_acceleration': 'infill_acceleration',
    'internal_solid_infill_acceleration': 'solid_infill_acceleration',
    'top_surface_acceleration': 'top_solid_infill_acceleration',
    'initial_layer_acceleration': 'first_layer_acceleration',
    # support
    'support_threshold_angle': 'support_material_threshold',
    'support_top_z_distance': 'support_material_contact_distance',
    'support_bottom_z_distance': 'support_material_bottom_contact_distance',
    'support_interface_spacing': 'support_material_interface_spacing',
    'support_interface_top_layers': 'support_material_interface_layers',
    'support_interface_bottom_layers': 'support_material_bottom_interface_layers',
    'support_base_pattern': 'support_material_pattern',
    'support_interface_pattern': 'support_material_interface_pattern',
    'support_base_pattern_spacing': 'support_material_spacing',
    'support_object_xy_distance': 'support_material_xy_spacing',
    'support_on_build_plate_only': 'support_material_buildplate_only',
    'support_angle': 'support_material_angle',
    'support_style': 'support_material_style',
    'support_filament': 'support_material_extruder',
    'support_interface_filament': 'support_material_interface_extruder',
    'support_interface_loop_pattern': 'support_material_interface_contact_loops',
    'enforce_support_layers': 'support_material_enforce_layers',
    'tree_support_branch_diameter': 'support_tree_branch_diameter',
    'tree_support_branch_angle': 'support_tree_angle',
    'tree_support_branch_angle_organic': 'support_tree_angle',
    'tree_support_branch_diameter_angle': 'support_tree_branch_diameter_angle',
    'tree_support_bramch_diameter_angle': 'support_tree_branch_diameter_angle',
    'tree_support_top_rate': 'support_tree_top_rate',
    'tree_support_tip_diameter': 'support_tree_tip_diameter',
    # bridging, travel, misc
    'bridge_flow': 'bridge_flow_ratio',
    'bridge_no_support': 'dont_support_bridges',
    'reduce_crossing_wall': 'avoid_crossing_perimeters',
    'max_travel_detour_distance': 'avoid_crossing_perimeters_max_detour',
    'seam_gap': 'seam_gap_distance',
    'brim_object_gap': 'brim_separation',
    'skirt_loops': 'skirts',
    'ironing_flow': 'ironing_flowrate',
    'fuzzy_skin_point_distance': 'fuzzy_skin_point_dist',
    'filename_format': 'output_filename_format',
    'resolution': 'gcode_resolution',
    'enable_prime_tower': 'wipe_tower',
    'prime_tower_width': 'wipe_tower_width',
    'prime_tower_brim_width': 'wipe_tower_brim_width',
    'xy_contour_compensation': 'xy_size_compensation',
    'spiral_mode': 'spiral_vase',
}

FILAMENT_RENAMES = {
    'nozzle_temperature': 'temperature',
    'nozzle_temperature_initial_layer': 'first_layer_temperature',
    'filament_flow_ratio': 'extrusion_multiplier',
    'filament_start_gcode': 'start_filament_gcode',
    'filament_end_gcode': 'end_filament_gcode',
    'filament_retraction_length': 'filament_retract_length',
    'filament_retraction_speed': 'filament_retract_speed',
    'filament_deretraction_speed': 'filament_deretract_speed',
    'filament_retraction_minimum_travel': 'filament_retract_before_travel',
    'filament_retract_when_changing_layer': 'filament_retract_layer_change',
    'filament_z_hop': 'filament_retract_lift',
    'fan_min_speed': 'min_fan_speed',
    'fan_max_speed': 'max_fan_speed',
    'fan_cooling_layer_time': 'fan_below_layer_time',
    'slow_down_layer_time': 'slowdown_below_layer_time',
    'slow_down_min_speed': 'min_print_speed',
    'close_fan_the_first_x_layers': 'disable_fan_first_layers',
    'overhang_fan_speed': 'bridge_fan_speed',
    'reduce_fan_stop_start_freq': 'fan_always_on',
    'default_filament_colour': 'filament_colour',
    # Orca's `pressure_advance` holds the value; PrusaSlicer 3.x uses
    # `pressure_advance` for the on/off enum and `pressure_advance_value` for it.
    'pressure_advance': 'pressure_advance_value',
    'enable_pressure_advance': 'pressure_advance',
}

# Enum values Orca spells differently.
ENUM_VALUES = {
    'fill_pattern': {'zigzag': 'zigzag', 'zig-zag': 'zigzag',
                     'tri-hexagon': 'stars', 'quartercubic': 'cubic',
                     'crosshatch': 'rectilinear', 'crosszag': 'zigzag',
                     'lockedzag': 'zigzag'},
    'top_fill_pattern': {'monotonicline': 'monotoniclines'},
    'bottom_fill_pattern': {'monotonicline': 'monotoniclines'},
    'support_material_style': {'default': 'grid', 'tree_slim': 'organic',
                               'tree_strong': 'organic', 'tree_hybrid': 'organic'},
    'support_material_pattern': {'default': 'rectilinear', 'lightning': 'rectilinear',
                                 'hollow': 'rectilinear', 'auto': 'rectilinear'},
    'support_material_interface_pattern': {'rectilinear_interlaced': 'rectilinear',
                                           'grid': 'rectilinear'},
    'seam_position': {'back': 'rear', 'aligned_back': 'rear', 'none': 'aligned'},
    'brim_type': {'auto_brim': 'outer_only', 'brim_ears': 'outer_only',
                  'painted': 'outer_only'},
    'fuzzy_skin': {'allwalls': 'all', 'hole': 'external',
                   'disabled_fuzzy': 'none'},
    'draft_shield': {'combined': 'enabled', 'perobject': 'enabled'},
}

# Orca's bed-type-specific temperatures; 3.x has one bed temperature, so the
# plate named by the machine's `default_bed_type` is the one that is carried.
PLATE_KEYS = {
    'Cool Plate': 'cool_plate_temp',
    'PLA Plate': 'cool_plate_temp',
    'Cool Plate (SuperTack)': 'supertack_plate_temp',
    'Supertack Plate': 'supertack_plate_temp',
    'Engineering Plate': 'eng_plate_temp',
    'High Temp Plate': 'hot_plate_temp',
    'Smooth PEI Plate': 'hot_plate_temp',
    'Textured PEI Plate': 'textured_plate_temp',
    'Textured Cool Plate': 'textured_cool_plate_temp',
}
PLATE_FALLBACK = ['hot_plate_temp', 'textured_plate_temp', 'eng_plate_temp',
                  'cool_plate_temp', 'supertack_plate_temp',
                  'textured_cool_plate_temp']

# Options both formats have but default differently, so an Orca profile that
# never mentions them still means something else than a PrusaSlicer one would.
# Each was read off OrcaSlicer's PrintConfig.cpp set_default_value() call.
# Only options whose difference changes the slice are listed - Orca's defaults
# are not injected wholesale.
ORCA_DEFAULTS = {
    'printer': {
        # Orca/Bambu machines address the extruder relatively; PrusaSlicer's
        # default is absolute, and 3.x refuses to slice on the mismatch.
        'use_relative_e_distances': '1',
        'gcode_flavor': 'marlin',
    },
    'print': {
        'thick_bridges': '0',
    },
    'filament': {},
}

KIND_TYPE = {'printer': 'machine', 'print': 'process', 'filament': 'filament'}

# Custom G-code refers to options by name, so Orca's names have to be rewritten
# inside the templates as well - `[nozzle_temperature_initial_layer]` means
# nothing to PrusaSlicer.  Orca-only placeholders are listed separately.
GCODE_KEYS = {'start_gcode', 'end_gcode', 'before_layer_gcode', 'layer_gcode',
              'toolchange_gcode', 'pause_print_gcode', 'start_filament_gcode',
              'end_filament_gcode', 'between_objects_gcode',
              'template_custom_gcode', 'output_filename_format'}
# keywords and functions of the placeholder language itself. `local` and `then`
# matter more than they look: a template that declares its own variables
# (`{local speed = min(travel_speed, 350); }`, which prusaslicer's own toolchange
# templates do) had `local` rewritten to `0`, and `0 0 = 350.0;` is not a
# template any more - 3.x refuses the whole thing, which only shows up on a
# print that actually changes tool
RESERVED_WORDS = {'if', 'else', 'elsif', 'endif', 'then', 'local', 'and', 'or',
                  'not', 'true', 'false', 'min', 'max', 'int', 'round', 'digits',
                  'zhop', 'interpolate_table', 'regex', 'empty', 'size'}

# Placeholders PrusaSlicer resolves at slicing time.  They are not config options,
# so they are not in the schema, and must not be mistaken for Orca-only settings.
# PrusaSlicer keeps these per filament, so inside a {..} expression they need an
# index; Orca's counterparts are scalars and its G-code writes them bare.
VECTOR_PLACEHOLDERS = {
    'temperature', 'first_layer_temperature', 'bed_temperature',
    'first_layer_bed_temperature', 'chamber_temperature',
    'chamber_minimal_temperature', 'filament_type', 'idle_temperature',
}

RUNTIME_PLACEHOLDERS = {
    'layer_z', 'layer_num', 'max_layer_z', 'total_layer_count', 'first_layer_print_min',
    'first_layer_print_max', 'first_layer_print_size', 'print_bed_min', 'print_bed_max',
    'print_bed_size', 'num_extruders', 'initial_extruder', 'initial_tool',
    'previous_extruder', 'next_extruder', 'current_extruder', 'is_extruder_used',
    'has_wipe_tower', 'has_single_extruder_multi_material_priming', 'current_object_idx',
    'toolchange_z', 'travel_to_z', 'in_start_gcode', 'printing_filament_types',
    'input_filename', 'input_filename_base', 'default_output_extension', 'print_time',
    'timestamp', 'day', 'month', 'year', 'hour', 'minute', 'second', 'plate_name',
    'extruded_weight_total', 'extruded_volume_total', 'extruded_weight',
    'extruded_volume', 'scale', 'total_weight', 'total_cost', 'total_toolchanges',
}
GCODE_PLACEHOLDERS = {
    'bed_temperature_initial_layer_single': 'first_layer_bed_temperature',
    'bed_temperature_initial_layer': 'first_layer_bed_temperature',
    'nozzle_temperature_initial_layer': 'first_layer_temperature',
    'nozzle_temperature': 'temperature',
    'hot_plate_temp_initial_layer': 'first_layer_bed_temperature',
    'hot_plate_temp': 'bed_temperature',
    'total_layer_number': 'total_layer_count',
    'layer_num': 'layer_num',
    'initial_extruder': 'initial_extruder',
    'previous_extruder': 'previous_extruder',
}

# Orca metadata that is not a setting.
ORCA_META = {
    'type', 'name', 'from', 'inherits', 'instantiation', 'setting_id', 'version',
    'filament_id', 'compatible_printers', 'compatible_printers_condition',
    'compatible_prints', 'compatible_prints_condition', 'upward_compatible_machine',
    'machine_tech', 'model_id', 'family', 'bed_model', 'bed_texture', 'url',
    'default_materials', 'sub_path', 'is_custom_defined', 'description',
    'printer_settings_id', 'print_settings_id', 'filament_settings_id',
    'default_print_profile', 'default_filament_profile', 'renamed_from',
    'default_bed_type',
}


class OrcaBundle:
    """An Orca/Bambu profile tree, presented like a PrusaSlicer 2.x bundle."""

    def __init__(self, index_path, note=None, extra_trees=(), valid_names=frozenset(),
                 fix_gcode=False):
        self.path = index_path
        self.note = note or (lambda _m: None)
        self.valid_names = set(valid_names)
        self.fix_gcode = fix_gcode
        self.index = files.read_json(index_path)
        root = os.path.dirname(os.path.abspath(index_path))
        stem = re.sub(r'\.json$', '', os.path.basename(index_path))
        self.root = os.path.join(root, stem)
        self.vendor = {'name': self.index.get('name', stem),
                       'repo_id': re.sub(r'[^a-z0-9]+', '-', stem.lower())}
        self._raw = {}
        # Orca keeps vendor-independent filaments in a shared library, and a
        # machine's default_materials point at those by name, so an extra tree
        # can be loaded alongside the vendor's own.
        trees = [self.root] + [self._tree_of(p) for p in extra_trees]
        for tree in trees:
            n = 0
            for f in glob.glob(os.path.join(tree, '**', '*.json'), recursive=True):
                try:
                    d = files.read_json(f)
                except json.JSONDecodeError as e:
                    self.note(f'skipped unreadable {os.path.basename(f)}: {e}')
                    continue
                if isinstance(d, dict) and d.get('name'):
                    self._raw.setdefault(d['name'], d)
                    n += 1
            if tree != self.root:
                self.note(f'loaded {n} preset(s) from {os.path.basename(tree)}')
        self._resolved = {}
        self._converted = {}

    # -- raw access -------------------------------------------------------- #
    def _resolve_raw(self, name, _seen=()):
        if name in self._resolved:
            return self._resolved[name]
        d = self._raw[name]
        out = {}
        parent = d.get('inherits')
        if parent and parent not in self._raw:
            self.note(f'{name!r} inherits {parent!r}, which is not in the profile '
                      f'tree; the values it would have contributed are missing')
        elif parent and parent not in _seen:
            out.update(self._resolve_raw(parent, _seen + (name,)))
        for k, v in d.items():
            if k != 'inherits':
                out[k] = v
        self._resolved[name] = out
        return out

    def _instantiable(self, kind):
        want = KIND_TYPE[kind]
        out = []
        for name, d in self._raw.items():
            if d.get('type') != want:
                continue
            inst = self._resolve_raw(name).get('instantiation', 'true')
            if str(inst).lower() == 'true':
                out.append(name)
        return sorted(out)

    # -- Bundle interface -------------------------------------------------- #
    def names(self, kind, leaves_only=True):
        return self._instantiable(kind)

    def printer_models(self):
        models = collections.OrderedDict()
        for name, d in self._raw.items():
            if d.get('type') != 'machine_model':
                continue
            nozzles = str(d.get('nozzle_diameter', '')).replace(',', ';')
            models[name] = {
                'name': d.get('name', name),
                'technology': (d.get('machine_tech') or 'FFF').upper(),
                'family': d.get('family', ''),
                'variants': nozzles,
                'bed_model': d.get('bed_model', ''),
                'bed_texture': d.get('bed_texture', ''),
                'default_materials': d.get('default_materials', ''),
            }
        if models:
            return models
        for name in self.names('printer'):
            kv = self.resolve('printer', name)
            mid = kv.get('printer_model') or name
            models.setdefault(mid, {'name': mid, 'technology': 'FFF'})
        return models

    def compat(self, kind, name):
        """Orca lists compatible machines outright, rather than as a condition.

        An empty list means no restriction - that is how the shared filament
        library ships its generic materials - so it becomes every printer this
        bundle defines.
        """
        kv = self._resolve_raw(name)
        lst = kv.get('compatible_printers')
        if isinstance(lst, str):
            lst = [lst] if lst else []
        if not lst:
            return ('list', set(self.names('printer')))
        return ('list', set(lst))

    def resolve(self, kind, name):
        """Return the preset as PrusaSlicer 2.x style `key = string` values."""
        cache_key = (kind, name)
        if cache_key in self._converted:
            return self._converted[cache_key]
        raw = self._resolve_raw(name)
        renames = {'printer': MACHINE_RENAMES, 'print': PROCESS_RENAMES,
                   'filament': FILAMENT_RENAMES}[kind]
        out = collections.OrderedDict()

        if kind == 'filament':
            raw = self._pick_plate_temp(raw)

        for k, v in raw.items():
            if k in ORCA_META:
                continue
            key = renames.get(k, k)
            val = self._flatten(v)
            if val is None:
                continue
            if key in ENUM_VALUES:
                val = ENUM_VALUES[key].get(val, val)
            if key in GCODE_KEYS:
                val = self._rewrite_gcode(val, renames)
                val = self._inline_orca_only(val, raw, key)
                if self._orca_script(val):
                    val = self._translate_script(val, key)
                if val is None:
                    continue
            out[key] = val

        for k in ('printer_model', 'printer_variant', 'nozzle_diameter',
                  'default_print_profile', 'default_filament_profile'):
            if k in raw:
                out[k] = self._flatten(raw[k]) or ''

        self._special(kind, raw, out)
        for k, v in ORCA_DEFAULTS[kind].items():
            if k not in out:
                out[k] = v
                self.note(f'{k} was not set; used Orca\'s default ({v!r}) rather '
                          f'than PrusaSlicer\'s, which differs')
        self._converted[cache_key] = out
        return out

    # -- helpers ----------------------------------------------------------- #
    def _rewrite_gcode(self, text, renames):
        # Orca's profiles carry backslash-escaped quotes inside expressions
        # ({if curr_bed_type==\"High Temp Plate\"}); PrusaSlicer's placeholder
        # parser wants plain quotes and rejects the escape.
        if '\\"' in text:
            text = text.replace('\\"', '"')
            self.note('custom G-code: unescaped \\" to " inside expressions '
                      '(3.x cannot parse the escaped form)')
        table = dict(GCODE_PLACEHOLDERS)
        for src, dst in renames.items():
            table.setdefault(src, dst)
        done = set()
        for src, dst in table.items():
            if src == dst or src not in text:
                continue
            pattern = r'(?<![A-Za-z_0-9])' + re.escape(src) + r'(?![A-Za-z_0-9])'
            text, n = re.subn(pattern, dst, text)
            if n:
                done.add(f'{src} -> {dst}')
        for d in sorted(done):
            self.note(f'custom G-code: renamed the {d} placeholder (Orca name)')
        for name in VECTOR_PLACEHOLDERS:
            # {x} -> {x[0]}; the [x] form already indexes itself
            pattern = r'\{\s*' + name + r'\s*\}'
            text, n = re.subn(pattern, '{' + name + '[0]}', text)
            if n:
                self.note(f'custom G-code: indexed {{{name}}} as {{{name}[0]}} '
                          f'(PrusaSlicer keeps it per filament)')
        return text

    def _translate_script(self, text, key):
        """Orca's script dialect into prusaslicer's own, or None if not sure.

        The two dialects share their expressions and their locals; what differs
        is that orca writes `if c then ... endif` and emits text by evaluating a
        string statement, where prusaslicer wraps text in `{if}...{endif}` and
        writes it outside the braces.  A refused translation drops the option:
        the alternative is a macro 3.x will not parse, which stops the slice as
        soon as the g-code is needed.
        """
        known = set(self.valid_names) | RUNTIME_PLACEHOLDERS \
            | set(GCODE_PLACEHOLDERS.values())
        got = orca_script.translate(text, known, self.note)
        if got is None:
            self.note(f'{key} is written in orca\'s script dialect and could not '
                      f'be translated into 3.x placeholders - dropped, because a '
                      f'template 3.x refuses stops the slice as soon as the '
                      f'g-code is needed. prusaslicer emits its own tool change; '
                      f'anything else this macro did has to be written by hand')
            return None
        self.note(f'{key} was translated from orca\'s script dialect into 3.x '
                  f'placeholders (`if ... then` became `{{if}}...{{endif}}`, '
                  f'string statements became text). read it before printing')
        return got

    @staticmethod
    def _orca_script(text):
        """True when a template is written in orca's script dialect.

        both slicers evaluate `{...}` blocks with locals and expressions, and
        prusaslicer's own toolchange templates look much like orca's - but orca
        also has `if cond then ... endif` and emits text by evaluating a string
        statement (`"G91\n";`), where prusaslicer wraps text in `{if}...{endif}`
        and writes it outside the braces. 3.x rejects the whole template on
        either, and a rejected toolchange template is only noticed on a print
        that changes tool.
        """
        return bool(re.search(r'(?<![A-Za-z_0-9])then(?![A-Za-z_0-9])', text)
                    or re.search(r'"\s*;', text))

    def _inline_orca_only(self, text, raw, key):
        """Replace references to Orca-only options with their literal value.

        Orca's custom G-code branches on settings 3.x does not have -
        `{if curr_bed_type == "High Temp Plate"}` and friends - and an unknown
        identifier makes 3.x refuse to export the G-code at all.  The profile
        knows what those settings are, so inlining the value keeps the branch
        deciding the same way it did in Orca.
        """
        if not self.valid_names:
            return text
        # a name the template declares or assigns to is its own variable, not a
        # setting to look up: rewriting it destroys the statement that defines it
        own = set(re.findall(r'\blocal\s+([A-Za-z_][A-Za-z_0-9]*)', text))
        own.update(re.findall(r'([A-Za-z_][A-Za-z_0-9]*)\s*(?:\[[^\]]*\])?\s*=(?!=)',
                              text))
        refs = set()
        for m in re.finditer(r'[\[\{]([^\]\}]{0,200})[\]\}]', text):
            # words inside string and regex literals are data, not option
            # references - and rewriting one corrupts the pattern it belongs to
            body = re.sub(r'[=!]~\s*/[^/]*/|"[^"]*"|\'[^\']*\'', ' ', m.group(1))
            refs.update(re.findall(r'[A-Za-z_][A-Za-z_0-9]*', body))
        known = dict(raw)
        if 'default_bed_type' in raw:
            known.setdefault('curr_bed_type', raw['default_bed_type'])
        for name in sorted(refs):
            if name in self.valid_names or name in GCODE_PLACEHOLDERS.values():
                continue
            if name in RESERVED_WORDS or name in RUNTIME_PLACEHOLDERS or name in own:
                continue
            word = r'(?<![A-Za-z_0-9])' + re.escape(name) + r'(?![A-Za-z_0-9])'
            if name in known:
                lit = self._flatten(known[name])
                try:
                    float(lit)
                    rep = lit
                except (TypeError, ValueError):
                    rep = '"' + str(lit).replace('"', '') + '"'
                text = re.sub(r'\[' + re.escape(name) + r'\]', str(lit), text)
                text = re.sub(word, rep, text)
                self.note(f'custom G-code: inlined {name}={lit!r}, an Orca-only '
                          f'setting with no 3.x counterpart')
            elif self.fix_gcode:
                text = re.sub(r'\[' + re.escape(name) + r'\]|\{\s*'
                              + re.escape(name) + r'\s*\}', '', text)
                # the literal has to match what the expression compares against,
                # or 3.x rejects the comparison instead of the identifier
                cmp_str = re.search(word + r'\s*[=!]=\s*["\']', text)
                cmp_num = re.search(word + r'\s*(?:[<>]=?|[=!]=)\s*-?\d', text)
                lit = '""' if cmp_str and not cmp_num else '0'
                text = re.sub(word, lit, text)
                self.note(f'custom G-code: neutralised {name} as {lit}, an Orca-only '
                          f'setting whose value this profile does not state '
                          f'(--fix-gcode)')
            else:
                self.note(f'custom G-code in {key} references {name}, which 3.x does '
                          f'not have and this profile does not state; the preset will '
                          f'not export G-code. Re-run with --fix-gcode')
        return text

    @staticmethod
    def _tree_of(index_path):
        """The preset tree an orca vendor index names.

        Falling back to the index's own directory would sweep in every unrelated
        profile beside it, which turns a filament library into fifteen extra
        vendors, so a tree that is not there is an error.
        """
        d = os.path.dirname(os.path.abspath(index_path))
        stem = re.sub(r'\.json$', '', os.path.basename(index_path))
        cand = os.path.join(d, stem)
        if os.path.isdir(cand):
            return cand
        if os.path.basename(d) == stem:        # index kept inside its own tree
            return d
        raise SourceError(f'{index_path} names no preset tree: expected a '
                          f'{stem}/ directory beside it')

    @staticmethod
    def _flatten(v):
        """Orca stores per-extruder values as arrays; 2.x comma-joins them."""
        if v is None:
            return None
        if isinstance(v, list):
            if not v:
                return ''
            return ','.join(str(x) for x in v)
        if isinstance(v, bool):
            return '1' if v else '0'
        return str(v)

    def _pick_plate_temp(self, raw):
        """Collapse Orca's per-plate bed temperatures onto one bed temperature."""
        plate = self._bed_type_for(raw)
        keys = ([PLATE_KEYS[plate]] if plate in PLATE_KEYS else []) + PLATE_FALLBACK
        raw = dict(raw)
        for suffix, target in (('', 'bed_temperature'),
                               ('_initial_layer', 'first_layer_bed_temperature')):
            for base in keys:
                k = base + suffix
                if k in raw and self._flatten(raw[k]) not in (None, ''):
                    raw[target] = raw[k]
                    break
        if plate:
            self.note(f'bed temperature taken from Orca\'s "{plate}" values '
                      f'(3.x has one bed temperature, Orca has one per plate type)')
        return raw

    def _bed_type_for(self, raw):
        for machine in (raw.get('compatible_printers') or []):
            if machine in self._raw:
                bt = self._resolve_raw(machine).get('default_bed_type')
                if bt:
                    return str(bt)
        return ''

    def _special(self, kind, raw, out):
        """Cases where one Orca option becomes two, or vice versa."""
        if kind == 'print':
            st = self._flatten(raw.get('support_type')) or ''
            if st:
                out['support_material'] = '0' if st == 'none' else '1'
                out['support_material_auto'] = '1' if '(auto)' in st else '0'
                if st.startswith('tree'):
                    out['support_material_style'] = 'organic'
            if 'enable_support' in raw:
                out['support_material'] = self._flatten(raw['enable_support'])
            gft = self._flatten(raw.get('gap_fill_target'))
            if gft is not None:
                out['gap_fill_enabled'] = '0' if gft == 'nowhere' else '1'
                out.pop('gap_fill_target', None)
            it = self._flatten(raw.get('ironing_type'))
            if it is not None:
                if it == 'no ironing':
                    out['ironing'] = '0'
                    out.pop('ironing_type', None)
                elif it in ('top', 'topmost', 'solid'):
                    out['ironing'] = '1'
                    out['ironing_type'] = it
                else:
                    out.pop('ironing_type', None)
            seq = self._flatten(raw.get('print_sequence'))
            if seq is not None:
                out['complete_objects'] = '1' if seq == 'by object' else '0'
                out.pop('print_sequence', None)
            order = self._flatten(raw.get('wall_infill_order'))
            if order is not None:
                out['external_perimeters_first'] = \
                    '1' if order.startswith('outer') else '0'
                out.pop('wall_infill_order', None)
            arc = self._flatten(raw.get('enable_arc_fitting'))
            if arc is not None:
                out['arc_fitting'] = 'emit_center' if arc in ('1', 'true') else 'disabled'
                out.pop('enable_arc_fitting', None)
            owt = self._flatten(raw.get('only_one_wall_top'))
            if owt is not None:
                out['top_one_perimeter_type'] = 'top' if owt in ('1', 'true') else 'none'
                out.pop('only_one_wall_top', None)
        elif kind == 'printer':
            lim = self._flatten(raw.get('emit_machine_limits_to_gcode'))
            if lim is not None:
                out['machine_limits_usage'] = \
                    'emit_to_gcode' if lim in ('1', 'true') else 'time_estimate_only'
                out.pop('emit_machine_limits_to_gcode', None)
        elif kind == 'filament':
            # Orca's filament_shrink is the printed size as a percentage of the
            # intended one (100% = no shrinkage); PrusaSlicer's compensation is
            # how much to scale up (0% = none).  Passing 100 straight through
            # scales the model by 2x and the slice explodes.
            # Orca's filament_shrinkage_compensation_z means the same printed-size
            # percentage, under the very name PrusaSlicer uses for a compensation,
            # so it would otherwise pass straight through as a 2x Z scale.
            for src, dst in (('filament_shrink', 'filament_shrinkage_compensation_xy'),
                             ('filament_shrinkage_compensation_z',
                              'filament_shrinkage_compensation_z')):
                sh = self._flatten(raw.get(src))
                if not sh:
                    continue
                try:
                    pct = float(str(sh).rstrip('%'))
                except ValueError:
                    out.pop(dst, None)
                    continue
                if pct > 0:
                    out[dst] = f'{(100.0 / pct - 1.0) * 100.0:g}%'
                else:
                    out.pop(dst, None)
            pa = self._flatten(raw.get('enable_pressure_advance'))
            if pa is not None:
                out['pressure_advance'] = 'enabled' if pa in ('1', 'true') else 'disabled'
            ch = self._flatten(raw.get('chamber_temperatures'))
            if ch:
                parts = [p for p in ch.split(',') if p.strip()]
                if parts:
                    out['chamber_temperature'] = parts[0]
            out.pop('chamber_temperatures', None)


def looks_like_orca(path):
    """True when `path` is an Orca/Bambu vendor index rather than a 2.x .ini."""
    if not path.lower().endswith('.json'):
        return False
    try:
        d = files.read_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(d, dict) and 'machine_model_list' in d


def check_targets(valid_names):
    """Report rename targets that are not options in the 3.x schema."""
    bad = []
    for table, label in ((MACHINE_RENAMES, 'machine'), (PROCESS_RENAMES, 'process'),
                         (FILAMENT_RENAMES, 'filament')):
        for src, dst in table.items():
            base = dst[len('filament_'):] if dst.startswith('filament_') else dst
            if dst not in valid_names and base not in valid_names:
                bad.append(f'{label}: {src} -> {dst}')
    return bad
