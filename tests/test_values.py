"""value conversion: the layer where a wrong answer is silent and expensive.

most of these are regressions. the bug each one caught is named in the test.
"""

from __future__ import annotations

import pytest

from ps2to3.values import Converter, Unset, parse_string_vector, unescape


@pytest.fixture
def conv(schema):
    return Converter(schema)


def coerce(conv, schema, kind, key, raw):
    return conv.coerce(key, raw, schema.pool(kind)[key])


# --------------------------------------------------------------------------- #
# string vectors
# --------------------------------------------------------------------------- #

def test_string_vector_keeps_quoted_items_whole():
    """2.x quotes an item that contains ';' or a newline.

    splitting on ';' alone tore gcode_substitutions into the wrong number of
    items, and 3.x rejected it as "invalid length".
    """
    raw = '";profile_gcode";"SET_VELOCITY_LIMIT ACCEL_TO_DECEL=4000";;'
    assert parse_string_vector(raw) == [
        ';profile_gcode', 'SET_VELOCITY_LIMIT ACCEL_TO_DECEL=4000', '', '']


def test_string_vector_empty_is_no_items():
    assert parse_string_vector('') == []
    assert parse_string_vector('   ') == []


def test_string_vector_unescapes_newlines():
    assert parse_string_vector('"a\\nb"') == ['a\nb']


def test_quoted_gcode_loses_its_serialisation_quotes(conv, schema):
    """start_filament_gcode is a vector in 2.x, a string in 3.x.

    reading it as a plain string left the serialisation quotes in the value, and
    the sliced g-code contained a literal '"' line.
    """
    raw = '"; FILAMENT_START_GCODE\\nM900 K0\\n"'
    got = coerce(conv, schema, 'filament', 'start_filament_gcode', raw)
    assert got == '; FILAMENT_START_GCODE\nM900 K0\n'
    assert not got.startswith('"')


def test_per_extruder_vector_reduces_to_the_first_value(conv, schema):
    """a multi-tool 2.x printer stores one value per extruder.

    3.x wants a scalar there; a comma-joined string was rejected outright.
    identical values across extruders lose nothing, so they reduce silently.
    """
    got = coerce(conv, schema, 'filament', 'temperature', '240,240,240,240')
    assert got == 240
    assert not conv.notes


def test_differing_per_extruder_values_are_reported(conv, schema):
    """dropping the other extruders' values is a real loss, so it is named."""
    got = coerce(conv, schema, 'filament', 'temperature', '240,215,190')
    assert got == 240
    assert any('per-extruder' in m for m in conv.notes)


def test_enum_vector_reduces_too(conv, schema):
    """a 3mf writes every filament option as a per-extruder vector."""
    got = coerce(conv, schema, 'filament', 'cooling_slowdown_logic',
                 'consistent_surface,consistent_surface')
    assert got == 'consistent_surface'


# --------------------------------------------------------------------------- #
# numbers and units
# --------------------------------------------------------------------------- #

def test_empty_numeric_means_unset(conv, schema):
    """2.x writes an empty value for "not set", which is not a conversion loss."""
    with pytest.raises(Unset):
        coerce(conv, schema, 'filament', 'filament_cost', '')


def test_percentage_where_3x_wants_millimetres_is_dropped(conv, schema):
    """avoid_crossing_perimeters_max_detour changed units between versions.

    a percentage has no millimetre equivalent, so it is dropped rather than
    guessed - and the caller is told.
    """
    with pytest.raises(ValueError, match='not a plain number'):
        coerce(conv, schema, 'print', 'avoid_crossing_perimeters_max_detour', '40%')


def test_percentage_survives_where_3x_accepts_one(conv, schema):
    assert coerce(conv, schema, 'print', 'infill_overlap', '15%') == '15%'


def test_machine_limits_pad_to_the_stealth_column(conv, schema):
    """2.x omits the second column when silent mode is off."""
    assert coerce(conv, schema, 'printer', 'machine_max_feedrate_x', '400') == [400, 400]


def test_bed_shape_becomes_a_point_list(conv, schema):
    got = coerce(conv, schema, 'printer', 'bed_shape', '0x0,200x0,200x200,0x200')
    assert got == ['0x0', '200x0', '200x200', '0x200']


# --------------------------------------------------------------------------- #
# enums that changed shape
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('support,auto,expected', [
    ('0', '0', 'none'),
    ('1', '1', 'everywhere'),
    ('1', '0', 'enforcers_only'),
])
def test_support_material_bool_pair_becomes_one_enum(conv, schema, support, auto,
                                                    expected):
    """2.x had a bool plus support_material_auto; 3.x has a three-way enum."""
    got = conv.values({'support_material': support, 'support_material_auto': auto},
                      'print')
    assert got['support_material'] == expected


def test_older_bool_reads_as_the_enum_it_became(conv, schema):
    """bundles predating the enum still write 1/0 for ensure_vertical_shell_thickness."""
    got = coerce(conv, schema, 'print', 'ensure_vertical_shell_thickness', '1')
    assert got == 'enabled'


def test_unknown_enum_value_is_rejected_not_passed_through(conv, schema):
    with pytest.raises(ValueError, match='is not one of'):
        coerce(conv, schema, 'print', 'fill_pattern', 'basketweave')


# --------------------------------------------------------------------------- #
# whole-preset conversion
# --------------------------------------------------------------------------- #

def test_thumbnails_get_a_format_suffix(conv):
    """2.x kept the format in a separate key, so a value can be a bare 300x300.

    3.x reads that as a 2-d vector and then refuses to store it in a string.
    """
    got = conv.values({'thumbnails': '300x300', 'thumbnails_format': 'PNG'}, 'printer')
    assert got['thumbnails'] == '300x300/PNG'


def test_thumbnails_with_a_format_are_left_alone(conv):
    got = conv.values({'thumbnails': '16x16/QOI, 400x300/PNG'}, 'printer')
    assert got['thumbnails'] == '16x16/QOI, 400x300/PNG'


def test_absolute_custom_bed_path_is_cleared(conv):
    """a config bundle records the bed as a path on the machine that exported it.

    it overrides the vendor bed model and points at nothing, and prusaslicer 3
    is unhappy loading it.
    """
    got = conv.values({'bed_custom_model': r'C:\Positron_bed.stl'}, 'printer')
    assert got['bed_custom_model'] == ''
    assert any('does not exist here' in m for m in conv.notes)


def test_existing_custom_bed_path_is_kept(conv, tmp_path):
    stl = tmp_path / 'bed.stl'
    stl.write_bytes(b'solid\n')
    got = conv.values({'bed_custom_model': str(stl)}, 'printer')
    assert got['bed_custom_model'] == str(stl)


def test_filament_prefixed_override_loses_its_prefix(conv):
    """3.x drops the filament_ prefixed form; the plain option is overridable."""
    got = conv.values({'filament_retract_length': '0.8'}, 'filament')
    assert got['retract_length'] == 0.8


def test_nil_override_is_not_carried(conv):
    """'nil' is how 2.x says "no override on this filament"."""
    got = conv.values({'filament_retract_length': 'nil'}, 'filament')
    assert 'retract_length' not in got


def test_unknown_key_is_dropped_and_named(conv):
    got = conv.values({'wipe_tower_rotation_angle': '0'}, 'print')
    assert got == {}
    assert any('wipe_tower_rotation_angle' in m for m in conv.notes)


def test_unescape_handles_escaped_backslash():
    assert unescape(r'a\\nb') == 'a\\nb'
    assert unescape(r'a\nb') == 'a\nb'
