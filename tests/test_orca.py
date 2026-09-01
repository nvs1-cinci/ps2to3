"""the orca/bambu reader.

the key mapping was derived by aligning orca's prusa profiles against
prusaslicer's own, so the tests that matter are the ones where the mapping is
counter-intuitive or where a value means the opposite thing.
"""

from __future__ import annotations

import json
import os

import pytest

from ps2to3.bundle import SourceError
from ps2to3.orca import (
    FILAMENT_RENAMES,
    MACHINE_RENAMES,
    PROCESS_RENAMES,
    OrcaBundle,
    check_targets,
    looks_like_orca,
)


@pytest.fixture
def tree(tmp_path):
    """Write an Orca vendor tree and return a factory for bundles over it."""
    def build(presets, index=None, vendor='Acme'):
        root = tmp_path / vendor
        for sub in ('machine', 'process', 'filament'):
            (root / sub).mkdir(parents=True, exist_ok=True)
        for name, d in presets.items():
            sub = {'machine': 'machine', 'machine_model': 'machine',
                   'process': 'process', 'filament': 'filament'}[d['type']]
            d = dict(d, name=name)
            (root / sub / (name.replace('/', '_') + '.json')).write_text(
                json.dumps(d), encoding='utf-8')
        idx = tmp_path / f'{vendor}.json'
        idx.write_text(json.dumps(index or {
            'name': vendor, 'version': '1.0.0', 'machine_model_list': [],
            'machine_list': [], 'process_list': [], 'filament_list': [],
        }), encoding='utf-8')
        return str(idx)
    return build


MACHINE = {
    'type': 'machine',
    'printer_model': 'AC1',
    'nozzle_diameter': ['0.4'],
    'printable_area': ['0x0', '200x0', '200x200', '0x200'],
    'printable_height': '200',
    'gcode_flavor': 'marlin2',
}


def bundle(tree, presets, **kw):
    notes = []
    b = OrcaBundle(tree(presets), note=notes.append, **kw)
    return b, notes


# --------------------------------------------------------------------------- #
# recognition
# --------------------------------------------------------------------------- #

def test_an_index_is_recognised_by_machine_model_list(tree):
    assert looks_like_orca(tree({}))


def test_an_ini_is_not_orca(vendor_ini):
    assert not looks_like_orca(vendor_ini)


def test_unparseable_json_is_not_orca(tmp_path):
    p = tmp_path / 'broken.json'
    p.write_text('{not json', encoding='utf-8')
    assert not looks_like_orca(str(p))


# --------------------------------------------------------------------------- #
# renames
# --------------------------------------------------------------------------- #

def test_every_rename_target_is_a_real_3x_option(schema):
    """a typo in the mapping silently drops the option instead of renaming it."""
    assert check_targets(schema.names()) == []


def test_overhang_speed_indices_are_not_off_by_one():
    """orca numbers overhang bands 1_4/2_4/3_4/4_4; the mapping is reversed.

    read off 14/14 value agreement between orca's and prusaslicer's own prusa
    profiles - the naive 1_4 -> overhang_speed_0 is wrong.
    """
    assert PROCESS_RENAMES['overhang_1_4_speed'] == 'overhang_speed_3'
    assert PROCESS_RENAMES['overhang_4_4_speed'] == 'overhang_speed_0'


def test_keys_misspelt_in_shipped_profiles_are_accepted():
    """these appear in profiles as published; dropping them loses the value."""
    assert MACHINE_RENAMES['detraction_speed'] == 'deretract_speed'
    assert PROCESS_RENAMES['inital_layer_height'] == 'first_layer_height'


def test_machine_keys_are_translated(tree):
    b, _ = bundle(tree, {'AC1 0.4': MACHINE})
    kv = b.resolve('printer', 'AC1 0.4')
    assert kv['bed_shape'] == '0x0,200x0,200x200,0x200'
    assert kv['max_print_height'] == '200'
    assert 'printable_area' not in kv


def test_per_extruder_arrays_are_comma_joined(tree):
    b, _ = bundle(tree, {'AC1 0.4': dict(MACHINE, retraction_length=['0.8', '0.8'])})
    assert b.resolve('printer', 'AC1 0.4')['retract_length'] == '0.8,0.8'


def test_json_booleans_become_2x_flags(tree):
    b, _ = bundle(tree, {'AC1 0.4': dict(MACHINE, retract_when_changing_layer=True)})
    assert b.resolve('printer', 'AC1 0.4')['retract_layer_change'] == '1'


def test_orca_metadata_is_not_treated_as_a_setting(tree):
    b, _ = bundle(tree, {'AC1 0.4': dict(MACHINE, setting_id='GM001', version='1.2',
                                         **{'from': 'system'})})
    kv = b.resolve('printer', 'AC1 0.4')
    for k in ('setting_id', 'version', 'from'):
        assert k not in kv


def test_inherits_is_resolved_and_the_child_wins(tree):
    b, _ = bundle(tree, {
        'AC1 common': dict(MACHINE, instantiation='false', retraction_length=['1.0']),
        'AC1 0.4': {'type': 'machine', 'inherits': 'AC1 common',
                    'retraction_length': ['0.6']},
    })
    kv = b.resolve('printer', 'AC1 0.4')
    assert kv['retract_length'] == '0.6'
    assert kv['max_print_height'] == '200'


def test_a_missing_parent_is_reported_rather_than_ignored(tree):
    b, notes = bundle(tree, {'AC1 0.4': dict(MACHINE, inherits='fdm base')})
    b.resolve('printer', 'AC1 0.4')
    assert any('not in the profile tree' in m for m in notes)


def test_uninstantiable_presets_are_not_offered(tree):
    b, _ = bundle(tree, {
        'AC1 base': dict(MACHINE, instantiation='false'),
        'AC1 0.4': dict(MACHINE),
    })
    assert b.names('printer') == ['AC1 0.4']


# --------------------------------------------------------------------------- #
# values that mean the opposite thing
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('shrink,expected', [
    ('100%', '0%'),      # orca: printed at 100% of intended = no shrinkage
    ('99%', '1.0101%'),  # printed 1% small -> scale up by 1/0.99
])
def test_filament_shrink_is_inverted_not_copied(tree, shrink, expected):
    """orca states the printed size; prusaslicer states the compensation.

    passing 100 through as a compensation scaled every model by 2x.
    """
    b, _ = bundle(tree, {'PLA': {'type': 'filament', 'filament_shrink': shrink}})
    kv = b.resolve('filament', 'PLA')
    assert kv['filament_shrinkage_compensation_xy'] == expected


def test_zero_shrink_is_left_alone_rather_than_dividing_by_it(tree):
    b, _ = bundle(tree, {'PLA': {'type': 'filament', 'filament_shrink': '0%'}})
    assert 'filament_shrinkage_compensation_xy' not in b.resolve('filament', 'PLA')


def test_relative_extrusion_default_is_orcas_not_prusaslicers(tree):
    """orca machines address the extruder relatively and often omit the option.

    inheriting prusaslicer's absolute default makes 3.x refuse to slice.
    """
    b, notes = bundle(tree, {'AC1 0.4': {k: v for k, v in MACHINE.items()}})
    kv = b.resolve('printer', 'AC1 0.4')
    assert kv['use_relative_e_distances'] == '1'
    assert any('use_relative_e_distances' in m for m in notes)


def test_a_stated_value_is_never_replaced_by_a_default(tree):
    b, _ = bundle(tree, {'AC1 0.4': dict(MACHINE, use_relative_e_distances='0')})
    assert b.resolve('printer', 'AC1 0.4')['use_relative_e_distances'] == '0'


# --------------------------------------------------------------------------- #
# one option becoming two, and vice versa
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('support_type,material,auto,style', [
    ('none', '0', '0', None),
    ('normal(auto)', '1', '1', None),
    ('normal(manual)', '1', '0', None),
    ('tree(auto)', '1', '1', 'organic'),
])
def test_support_type_splits_into_the_2x_trio(tree, support_type, material, auto, style):
    b, _ = bundle(tree, {'p': {'type': 'process', 'support_type': support_type}})
    kv = b.resolve('print', 'p')
    assert kv['support_material'] == material
    assert kv['support_material_auto'] == auto
    assert kv.get('support_material_style') == style


def test_print_sequence_becomes_complete_objects(tree):
    b, _ = bundle(tree, {'p': {'type': 'process', 'print_sequence': 'by object'}})
    kv = b.resolve('print', 'p')
    assert kv['complete_objects'] == '1'
    assert 'print_sequence' not in kv


def test_wall_order_becomes_external_perimeters_first(tree):
    b, _ = bundle(tree, {'p': {'type': 'process',
                               'wall_infill_order': 'outer wall/inner wall/infill'}})
    assert b.resolve('print', 'p')['external_perimeters_first'] == '1'


def test_arc_fitting_becomes_an_enum(tree):
    b, _ = bundle(tree, {'p': {'type': 'process', 'enable_arc_fitting': '1'}})
    assert b.resolve('print', 'p')['arc_fitting'] == 'emit_center'


def test_no_ironing_clears_the_type_rather_than_passing_it_on(tree):
    b, _ = bundle(tree, {'p': {'type': 'process', 'ironing_type': 'no ironing'}})
    kv = b.resolve('print', 'p')
    assert kv['ironing'] == '0'
    assert 'ironing_type' not in kv


def test_orca_only_ironing_type_is_dropped_not_passed_as_an_enum(tree):
    b, _ = bundle(tree, {'p': {'type': 'process', 'ironing_type': 'topmost_only'}})
    assert 'ironing_type' not in b.resolve('print', 'p')


def test_machine_limits_flag_becomes_a_usage_enum(tree):
    b, _ = bundle(tree, {'AC1 0.4': dict(MACHINE, emit_machine_limits_to_gcode='0')})
    kv = b.resolve('printer', 'AC1 0.4')
    assert kv['machine_limits_usage'] == 'time_estimate_only'
    assert 'emit_machine_limits_to_gcode' not in kv


def test_chamber_temperatures_vector_becomes_one_temperature(tree):
    b, _ = bundle(tree, {'PLA': {'type': 'filament',
                                 'chamber_temperatures': ['35', '35']}})
    kv = b.resolve('filament', 'PLA')
    assert kv['chamber_temperature'] == '35'
    assert 'chamber_temperatures' not in kv


def test_orca_enum_values_map_onto_3x_ones(tree):
    b, _ = bundle(tree, {'p': {'type': 'process', 'sparse_infill_pattern': 'crosshatch',
                               'seam_position': 'aligned_back'}})
    kv = b.resolve('print', 'p')
    assert kv['fill_pattern'] == 'rectilinear'
    assert kv['seam_position'] == 'rear'


# --------------------------------------------------------------------------- #
# per-plate bed temperatures
# --------------------------------------------------------------------------- #

def test_bed_temperature_comes_from_the_machines_own_plate(tree):
    b, notes = bundle(tree, {
        'AC1 0.4': dict(MACHINE, default_bed_type='Textured PEI Plate'),
        'PETG': {'type': 'filament', 'compatible_printers': ['AC1 0.4'],
                 'hot_plate_temp': ['90'], 'textured_plate_temp': ['85'],
                 'textured_plate_temp_initial_layer': ['80']},
    })
    kv = b.resolve('filament', 'PETG')
    assert kv['bed_temperature'] == '85'
    assert kv['first_layer_bed_temperature'] == '80'
    assert any('Textured PEI Plate' in m for m in notes)


def test_bed_temperature_falls_back_when_no_plate_is_named(tree):
    b, _ = bundle(tree, {'PETG': {'type': 'filament', 'eng_plate_temp': ['100'],
                                  'cool_plate_temp': ['60']}})
    assert b.resolve('filament', 'PETG')['bed_temperature'] == '100'


# --------------------------------------------------------------------------- #
# custom g-code
# --------------------------------------------------------------------------- #

def test_orca_option_names_inside_gcode_are_renamed(tree):
    b, notes = bundle(tree, {'AC1 0.4': dict(
        MACHINE, machine_start_gcode='M104 S[nozzle_temperature_initial_layer]\n')})
    kv = b.resolve('printer', 'AC1 0.4')
    assert kv['start_gcode'] == 'M104 S[first_layer_temperature]\n'
    assert any('renamed' in m for m in notes)


def test_escaped_quotes_inside_an_expression_are_unescaped(tree):
    """3.x's placeholder parser rejects \\" and refuses the whole template."""
    b, notes = bundle(tree, {'AC1 0.4': dict(
        MACHINE, machine_start_gcode='{if curr_bed_type==\\"High Temp Plate\\"}M140{endif}')})
    got = b.resolve('printer', 'AC1 0.4')['start_gcode']
    assert '\\"' not in got
    assert any('unescaped' in m for m in notes)


def test_a_per_filament_placeholder_is_indexed_when_interpolated_bare(tree):
    """prusaslicer keeps temperature per filament; orca's is a scalar.

    {temperature} therefore has to become {temperature[0]}; the [temperature]
    form indexes itself, and orca's profiles index it themselves inside
    expressions, so only the bare interpolation is rewritten.
    """
    b, notes = bundle(tree, {'AC1 0.4': dict(
        MACHINE, machine_start_gcode='M104 S{temperature}\nM140 S[bed_temperature]')})
    got = b.resolve('printer', 'AC1 0.4')['start_gcode']
    assert got == 'M104 S{temperature[0]}\nM140 S[bed_temperature]'
    assert any('indexed {temperature}' in m for m in notes)


def test_an_orca_only_setting_the_profile_states_is_inlined(tree, schema):
    """the branch keeps deciding the way orca decided it."""
    b, notes = bundle(tree, {'AC1 0.4': dict(
        MACHINE, default_bed_type='High Temp Plate',
        machine_start_gcode='{if curr_bed_type=="High Temp Plate"}M140 S100{endif}')},
        valid_names=schema.names())
    got = b.resolve('printer', 'AC1 0.4')['start_gcode']
    assert 'curr_bed_type' not in got
    assert '"High Temp Plate"=="High Temp Plate"' in got
    assert any('inlined' in m for m in notes)


def test_an_unstated_orca_only_setting_is_reported_not_silently_kept(tree, schema):
    b, notes = bundle(tree, {'AC1 0.4': dict(
        MACHINE, machine_start_gcode='{if activate_air_filtration[0]}M106 P3{endif}')},
        valid_names=schema.names())
    b.resolve('printer', 'AC1 0.4')
    assert any('will not export' in m and 'activate_air_filtration' in m for m in notes)


def test_fix_gcode_neutralises_an_unstated_setting_to_match_its_comparison(tree, schema):
    b, _ = bundle(tree, {'AC1 0.4': dict(
        MACHINE, machine_start_gcode='{if chamber_type=="closed"}M141{endif}')},
        valid_names=schema.names(), fix_gcode=True)
    got = b.resolve('printer', 'AC1 0.4')['start_gcode']
    assert 'chamber_type' not in got
    assert '""=="closed"' in got


def test_words_inside_a_string_literal_are_not_taken_for_options(tree, schema):
    b, notes = bundle(tree, {'AC1 0.4': dict(
        MACHINE, machine_start_gcode='{if filament_type[0]=="MARKER_PLA"}M117{endif}')},
        valid_names=schema.names())
    b.resolve('printer', 'AC1 0.4')
    assert not any('MARKER_PLA' in m for m in notes)


def test_words_inside_a_regex_literal_are_not_taken_for_options(tree, schema):
    """rewriting one would corrupt the pattern rather than fix the template."""
    body = '{if printer_notes=~/.*SOME_MARKER.*/}M117 marked{endif}'
    b, notes = bundle(tree, {'AC1 0.4': dict(MACHINE, machine_start_gcode=body)},
                      valid_names=schema.names(), fix_gcode=True)
    assert b.resolve('printer', 'AC1 0.4')['start_gcode'] == body
    assert not any('SOME_MARKER' in m for m in notes)


def test_runtime_placeholders_are_not_taken_for_orca_only_settings(tree, schema):
    b, notes = bundle(tree, {'AC1 0.4': dict(
        MACHINE, machine_start_gcode='; layer [layer_num] of [total_layer_count]')},
        valid_names=schema.names())
    b.resolve('printer', 'AC1 0.4')
    assert not [m for m in notes if 'custom G-code' in m]


# --------------------------------------------------------------------------- #
# compatibility and models
# --------------------------------------------------------------------------- #

def test_an_empty_compatible_list_means_every_printer(tree):
    """that is how the shared filament library ships generic materials."""
    b, _ = bundle(tree, {
        'AC1 0.4': MACHINE,
        'AC1 0.6': dict(MACHINE, nozzle_diameter=['0.6']),
        'Generic PLA': {'type': 'filament', 'compatible_printers': []},
    })
    kind, names = b.compat('filament', 'Generic PLA')
    assert kind == 'list'
    assert names == {'AC1 0.4', 'AC1 0.6'}


def test_compatibility_is_a_list_of_machines_not_a_condition(tree):
    b, _ = bundle(tree, {
        'AC1 0.4': MACHINE,
        'AC1 0.6': dict(MACHINE, nozzle_diameter=['0.6']),
        'PLA fine': {'type': 'filament', 'compatible_printers': ['AC1 0.4']},
    })
    assert b.compat('filament', 'PLA fine') == ('list', {'AC1 0.4'})


def test_machine_models_carry_their_nozzles_as_variants(tree):
    b, _ = bundle(tree, {
        'Acme One': {'type': 'machine_model', 'nozzle_diameter': '0.4,0.6',
                     'machine_tech': 'fdm', 'family': 'Acme',
                     'bed_model': 'ac1_bed.stl', 'bed_texture': 'ac1_bed.svg'},
    })
    m = b.printer_models()['Acme One']
    assert m['variants'] == '0.4;0.6'
    assert m['technology'] == 'FDM'
    assert m['bed_model'] == 'ac1_bed.stl'


def test_models_are_synthesised_when_the_tree_declares_none(tree):
    b, _ = bundle(tree, {'AC1 0.4': MACHINE})
    assert list(b.printer_models()) == ['AC1']


# --------------------------------------------------------------------------- #
# the shared filament library
# --------------------------------------------------------------------------- #

def test_an_extra_tree_is_loaded_alongside_the_vendors_own(tmp_path, tree):
    idx = tree({'AC1 0.4': MACHINE})
    lib_dir = tmp_path / 'OrcaFilamentLibrary' / 'filament'
    lib_dir.mkdir(parents=True)
    (lib_dir / 'pla.json').write_text(json.dumps({
        'type': 'filament', 'name': 'Generic PLA @System',
        'filament_type': ['PLA'], 'nozzle_temperature': ['210']}), encoding='utf-8')
    (tmp_path / 'OrcaFilamentLibrary.json').write_text(json.dumps(
        {'name': 'OrcaFilamentLibrary', 'machine_model_list': []}), encoding='utf-8')

    notes = []
    b = OrcaBundle(idx, note=notes.append,
                   extra_trees=(str(tmp_path / 'OrcaFilamentLibrary.json'),))
    assert 'Generic PLA @System' in b.names('filament')
    assert any('loaded 1 preset' in m for m in notes)


def test_the_vendors_own_preset_wins_over_the_librarys(tmp_path, tree):
    idx = tree({'AC1 0.4': MACHINE,
                'Generic PLA': {'type': 'filament', 'nozzle_temperature': ['205']}})
    lib = tmp_path / 'Lib'
    (lib / 'filament').mkdir(parents=True)
    (lib / 'filament' / 'pla.json').write_text(json.dumps({
        'type': 'filament', 'name': 'Generic PLA',
        'nozzle_temperature': ['999']}), encoding='utf-8')
    (tmp_path / 'Lib.json').write_text(json.dumps({'name': 'Lib'}), encoding='utf-8')

    b = OrcaBundle(idx, extra_trees=(str(tmp_path / 'Lib.json'),))
    assert b.resolve('filament', 'Generic PLA')['temperature'] == '205'


def test_a_library_index_with_no_tree_beside_it_is_an_error(tmp_path, tree):
    """the fallback used to be the index's own directory.

    pointing at a json that sits among other vendors' trees then loaded all of
    them, and one U1 conversion came out with fifteen printer models.
    """
    idx = tree({'AC1 0.4': MACHINE})
    (tmp_path / 'Lib.json').write_text(json.dumps({'name': 'Lib'}), encoding='utf-8')
    with pytest.raises(SourceError, match='names no preset tree'):
        OrcaBundle(idx, extra_trees=(str(tmp_path / 'Lib.json'),))


def test_an_index_kept_inside_its_own_tree_still_resolves(tmp_path, tree):
    idx = tree({'AC1 0.4': MACHINE})
    lib = tmp_path / 'Lib'
    lib.mkdir()
    (lib / 'Lib.json').write_text(json.dumps({'name': 'Lib'}), encoding='utf-8')
    (lib / 'pla.json').write_text(json.dumps({
        'type': 'filament', 'name': 'Lib PLA', 'nozzle_temperature': ['210']}),
        encoding='utf-8')
    b = OrcaBundle(idx, extra_trees=(str(lib / 'Lib.json'),))
    assert 'Lib PLA' in b.names('filament')


def test_an_unreadable_preset_is_skipped_and_named(tmp_path, tree):
    idx = tree({'AC1 0.4': MACHINE})
    bad = os.path.join(os.path.dirname(idx), 'Acme', 'process', 'broken.json')
    with open(bad, 'w', encoding='utf-8') as fh:
        fh.write('{ "type": "process",')
    notes = []
    OrcaBundle(idx, note=notes.append)
    assert any('skipped unreadable broken.json' in m for m in notes)


def test_filament_renames_cover_the_temperature_vocabulary():
    assert FILAMENT_RENAMES['nozzle_temperature'] == 'temperature'
    assert FILAMENT_RENAMES['nozzle_temperature_initial_layer'] == \
        'first_layer_temperature'


# --------------------------------------------------------------------------- #
# templates that declare their own variables
# --------------------------------------------------------------------------- #

SCRIPT_TEMPLATE = """{
local max_speed_toolchange = 350.0;
local speed_toolchange = max_speed_toolchange;
if travel_speed < max_speed_toolchange then
      speed_toolchange = travel_speed;
endif
"G1 F" + (speed_toolchange * 60) + "
";
}"""


def test_a_templates_own_local_variables_are_left_alone(tree, schema):
    """the u1's toolchange macro declares its own locals.

    `--fix-gcode` rewrote `local`, `position` and the declared names to `0`,
    which turned the macro into `0 0 = 350.0;`. 3.x refuses a template it cannot
    parse, and a refused toolchange template stops the slice the moment a tool
    change is needed: a multi-material print failed with `(38,
    [toolchange_gcode])` and no g-code, while single-tool prints were fine.
    """
    body = '{local speed = min(travel_speed, 350.0); speed = speed * 60;}'
    b, notes = bundle(tree, {'AC1 0.4': dict(MACHINE, machine_start_gcode=body)},
                      valid_names=schema.names(), fix_gcode=True)
    got = b.resolve('printer', 'AC1 0.4')['start_gcode']
    assert got == body
    assert not any('neutralised' in m for m in notes)


def test_local_and_then_are_keywords_not_settings():
    from ps2to3.orca import RESERVED_WORDS
    assert {'local', 'then'} <= RESERVED_WORDS


def test_an_assigned_name_is_not_taken_for_a_setting(tree, schema):
    b, notes = bundle(tree, {'AC1 0.4': dict(
        MACHINE, machine_start_gcode='{e_retracted[0] = 1.6}\nG1 E-1.6')},
        valid_names=schema.names(), fix_gcode=True)
    assert 'e_retracted[0] = 1.6' in b.resolve('printer', 'AC1 0.4')['start_gcode']
    assert not any('e_retracted' in m for m in notes)


def test_an_orca_script_template_is_translated_and_named(tree, schema):
    """3.x has locals and expressions but not orca's `if ... then` or its string
    statements, so the reader turns the control flow inside out."""
    b, notes = bundle(tree, {'AC1 0.4': dict(
        MACHINE, change_filament_gcode=SCRIPT_TEMPLATE)},
        valid_names=schema.names(), fix_gcode=True)
    got = b.resolve('printer', 'AC1 0.4')['toolchange_gcode']
    assert '{if travel_speed < max_speed_toolchange}' in got
    assert 'G1 F{(speed_toolchange * 60)}' in got
    assert 'then' not in got
    assert any('was translated' in m and 'toolchange_gcode' in m for m in notes)


def test_a_template_that_will_not_translate_is_dropped_and_named(tree, schema):
    """a macro that drives a tool head is never shipped half-translated."""
    b, notes = bundle(tree, {'AC1 0.4': dict(
        MACHINE, change_filament_gcode='{if layer_num == 0 then "M17\n";}')},
        valid_names=schema.names(), fix_gcode=True)
    assert 'toolchange_gcode' not in b.resolve('printer', 'AC1 0.4')
    assert any('could not be translated' in m for m in notes)


def test_a_prusaslicer_style_local_block_is_kept(tree, schema):
    """prusaslicer's own toolchange templates open with exactly this shape."""
    body = ('{\n  local speed_tc = min(travel_speed, 350.0) * 60;\n'
            '  local target = temperature[next_extruder];\n}\n'
            'M109 S{target}\nG1 F{speed_tc}')
    b, notes = bundle(tree, {'AC1 0.4': dict(MACHINE, change_filament_gcode=body)},
                      valid_names=schema.names(), fix_gcode=True)
    assert b.resolve('printer', 'AC1 0.4')['toolchange_gcode'] == body
    assert not any('script dialect' in m for m in notes)


def test_a_quoted_comparison_is_not_mistaken_for_a_string_statement(tree, schema):
    body = '{if filament_type[0] == "PLA"}M104 S210{endif}'
    b, _notes = bundle(tree, {'AC1 0.4': dict(MACHINE, machine_start_gcode=body)},
                       valid_names=schema.names(), fix_gcode=True)
    assert b.resolve('printer', 'AC1 0.4')['start_gcode'] == body
