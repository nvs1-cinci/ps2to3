"""custom g-code placeholders, and reading the three source shapes."""

from __future__ import annotations

import json
import os
import zipfile

import pytest

from ps2to3.bundle import Bundle, SourceError, ini_from_3mf, open_bundle
from ps2to3.gcode import migrate_gcode


def notes_of():
    seen = []
    return seen, seen.append


# --------------------------------------------------------------------------- #
# placeholders
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('old,new', [
    ('printer_preset', 'printer_settings_id'),
    ('print_preset', 'print_settings_id'),
    ('filament_preset', 'filament_settings_id'),
])
def test_renamed_placeholder_is_rewritten(old, new):
    """verified against 3.0.0-alpha10: the old names abort the g-code export."""
    seen, note = notes_of()
    got = migrate_gcode(f'; made by [{old}]', note)
    assert got == f'; made by [{new}]'
    assert any(old in m for m in seen)


def test_a_placeholder_with_no_counterpart_is_reported_not_silently_kept():
    seen, note = notes_of()
    got = migrate_gcode('; on [physical_printer_preset]', note, fix_removed=False)
    assert got == '; on [physical_printer_preset]'
    assert any('will not export' in m for m in seen)


def test_fix_gcode_neutralises_an_interpolation():
    seen, note = notes_of()
    got = migrate_gcode('; on [physical_printer_preset]', note, fix_removed=True)
    assert got == '; on '
    assert any('neutralised' in m for m in seen)


def test_fix_gcode_neutralises_a_bare_use_inside_an_expression():
    """snapmaker branches on it: {if physical_printer_preset =~ /.../}.

    stripping only the bracketed form left the bare identifier, and 3.x refused
    the whole template.
    """
    seen, note = notes_of()
    got = migrate_gcode('{if physical_printer_preset =~/.*IDEX.*/}M605{endif}',
                        note, fix_removed=True)
    assert 'physical_printer_preset' not in got
    assert '""' in got


def test_a_placeholder_that_only_looks_similar_is_left_alone():
    seen, note = notes_of()
    body = '; my_printer_preset_backup is mine'
    assert migrate_gcode(body, note) == body
    assert not seen


# --------------------------------------------------------------------------- #
# 2.x ini
# --------------------------------------------------------------------------- #

def test_blank_lines_do_not_join_onto_the_previous_value(write):
    """2.x escapes newlines, so a value never spans lines.

    treating a blank line as a continuation appended it to the value above and
    changed notes, gcode and every other text option.
    """
    path = write('a.ini', """
        [print:one]
        layer_height = 0.2

        notes = HF

        [print:two]
        layer_height = 0.3
        """)
    b = Bundle(path)
    assert b.sections['print:one']['layer_height'] == '0.2'
    assert b.sections['print:one']['notes'] == 'HF'
    assert b.sections['print:two']['layer_height'] == '0.3'


def test_comments_are_ignored(write):
    path = write('a.ini', """
        # a comment
        [print:one]
        ; another
        layer_height = 0.2
        """)
    assert Bundle(path).sections['print:one'] == {'layer_height': '0.2'}


def test_inherits_resolves_deepest_first(write):
    path = write('a.ini', """
        [print:*base*]
        layer_height = 0.2
        perimeters = 2

        [print:*mid*]
        inherits = *base*
        perimeters = 3

        [print:leaf]
        inherits = *mid*
        fill_density = 20%
        """)
    got = Bundle(path).resolve('print', 'leaf')
    assert got == {'layer_height': '0.2', 'perimeters': '3', 'fill_density': '20%'}


def test_an_inherits_cycle_is_an_error_not_a_hang(write):
    path = write('a.ini', """
        [print:a]
        inherits = b

        [print:b]
        inherits = a
        """)
    with pytest.raises(ValueError, match='cycle'):
        Bundle(path).resolve('print', 'a')


def test_intermediate_presets_are_not_offered_as_leaves(write):
    path = write('a.ini', """
        [print:*common*]
        layer_height = 0.2

        [print:real]
        inherits = *common*
        """)
    assert Bundle(path).names('print') == ['real']


def test_models_are_synthesised_when_a_config_bundle_declares_none(write):
    """a bundle exported from the gui has no printer_model section."""
    path = write('cfg.ini', """
        [printer:My Machine 0.4 nozzle]
        printer_model = MINE
        nozzle_diameter = 0.4
        """)
    assert list(Bundle(path).printer_models()) == ['MINE']


# --------------------------------------------------------------------------- #
# 3mf
# --------------------------------------------------------------------------- #

def make_3mf(path, config):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('3D/3dmodel.model', '<model/>')
        z.writestr('Metadata/Slic3r_PE.config', config)
    return str(path)


def test_3mf_config_becomes_one_printer_print_and_filament(tmp_path, schema):
    path = make_3mf(tmp_path / 'cube.3mf', '\n'.join([
        '; generated by PrusaSlicer 2.9.6',
        '; layer_height = 0.2',
        '; perimeters = 3',
        '; nozzle_diameter = 0.4',
        '; max_print_height = 210',
        '; filament_type = PETG',
        '; temperature = 240',
        '; print_settings_id = 0.20mm SPEED',
        '; printer_settings_id = My Printer 0.4',
        '; filament_settings_id = Generic PETG',
    ]))
    text = ini_from_3mf(path, schema)
    assert '[print:0.20mm SPEED]' in text
    assert '[printer:My Printer 0.4]' in text
    assert '[filament:Generic PETG]' in text
    assert 'perimeters = 3' in text
    assert 'temperature = 240' in text


def test_3mf_without_a_config_is_rejected_clearly(tmp_path, schema):
    path = tmp_path / 'plain.3mf'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('3D/3dmodel.model', '<model/>')
    with pytest.raises(SystemExit, match='Slic3r_PE.config'):
        ini_from_3mf(str(path), schema)


def test_reading_a_3mf_leaves_nothing_beside_it(tmp_path, schema):
    """the source can sit on read-only media, or in a folder that is not ours."""
    src = tmp_path / 'models'
    src.mkdir()
    path = make_3mf(src / 'cube.3mf', '; layer_height = 0.2\n; nozzle_diameter = 0.4')
    b = open_bundle(path, schema=schema)
    assert os.listdir(src) == ['cube.3mf']
    assert not b.path.startswith(str(src))


def test_a_source_that_is_not_there_says_so(tmp_path):
    with pytest.raises(SourceError, match='does not exist'):
        open_bundle(str(tmp_path / 'typo.ini'))


def test_a_directory_given_as_a_source_says_so(tmp_path):
    with pytest.raises(SourceError, match='is a directory'):
        open_bundle(str(tmp_path))


def test_open_bundle_needs_a_schema_for_a_3mf(tmp_path):
    path = make_3mf(tmp_path / 'c.3mf', '; layer_height = 0.2')
    with pytest.raises(SourceError, match='schema'):
        open_bundle(path)


# --------------------------------------------------------------------------- #
# source selection
# --------------------------------------------------------------------------- #

def test_an_orca_index_is_recognised_by_its_content(tmp_path):
    idx = tmp_path / 'Acme.json'
    idx.write_text(json.dumps({'name': 'Acme', 'machine_model_list': [],
                               'machine_list': [], 'process_list': [],
                               'filament_list': []}), encoding='utf-8')
    (tmp_path / 'Acme').mkdir()
    bundle = open_bundle(str(idx))
    assert bundle.vendor['name'] == 'Acme'


def test_a_filament_library_only_applies_to_orca_input(vendor_ini):
    with pytest.raises(SourceError, match='orca'):
        open_bundle(vendor_ini, extra_trees=('somewhere.json',))
