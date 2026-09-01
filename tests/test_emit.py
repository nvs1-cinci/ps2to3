"""yaml emission. a mangled multi-line value is the least visible failure here."""

from __future__ import annotations

import base64
import uuid

import yaml

from ps2to3.emit import mkid, slug, yvalues


def render(mapping):
    """emit a values mapping and read it back the way prusaslicer will.

    the trailing newline matters: the emitter ends every document with one, and
    a block scalar at end of input without it loses its own final newline.
    """
    text = 'values:\n' + '\n'.join(yvalues(mapping, 2)) + '\n'
    return yaml.safe_load(text)['values']


def test_multi_line_value_round_trips():
    body = 'G28 ; home\nM104 S210\n\nM84'
    assert render({'start_gcode': body})['start_gcode'] == body


def test_trailing_newline_survives():
    """a block scalar chomps the final newline unless the indicator says otherwise.

    2.x filament g-code commonly ends with one, and losing it changed the value.
    """
    body = '; filament start\nM900 K0\n'
    assert render({'start_filament_gcode': body})['start_filament_gcode'] == body


def test_several_trailing_newlines_survive():
    body = 'M104 S0\n\n\n'
    assert render({'end_gcode': body})['end_gcode'] == body


def test_value_that_is_only_a_newline_survives():
    """a block scalar with no content reads back as empty, not as a newline."""
    assert render({'end_filament_gcode': '\n'})['end_filament_gcode'] == '\n'


def test_trailing_whitespace_survives():
    """block scalars cannot carry a line with trailing spaces."""
    body = 'M104 S210   \nM84'
    assert render({'start_gcode': body})['start_gcode'] == body


def test_tab_indented_line_survives():
    body = 'G28\n\tG1 X0'
    assert render({'start_gcode': body})['start_gcode'] == body


def test_single_quote_in_a_value_survives():
    assert render({'notes': "don't remove"})['notes'] == "don't remove"


def test_booleans_and_numbers_keep_their_type():
    got = render({'wipe_tower': True, 'perimeters': 2, 'layer_height': 0.2})
    assert got == {'wipe_tower': True, 'perimeters': 2, 'layer_height': 0.2}


def test_percentage_stays_a_string():
    assert render({'fill_density': '15%'})['fill_density'] == '15%'


def test_list_renders_as_a_flow_sequence():
    got = render({'bed_shape': ['0x0', '200x0']})
    assert got['bed_shape'] == ['0x0', '200x0']


# --------------------------------------------------------------------------- #
# ids
# --------------------------------------------------------------------------- #

def test_preset_id_is_a_base64_uuid4():
    """3.x parses a preset id as a uuid.

    22 characters of arbitrary base64 are accepted by the yaml reader and then
    silently produce no presets at all.
    """
    got = mkid('acme/print/0.20mm')
    parsed = uuid.UUID(bytes=base64.b64decode(got + '=='))
    assert parsed.version == 4
    assert str(parsed.variant) == 'specified in RFC 4122'
    assert len(got) == 22
    assert '=' not in got


def test_preset_id_is_stable_for_the_same_seed():
    assert mkid('acme/print/x') == mkid('acme/print/x')


def test_preset_id_differs_per_seed():
    assert mkid('acme/print/x') != mkid('acme/print/y')


def test_slug_keeps_only_path_safe_characters():
    assert slug('Prusa Pro HT90 - High Temp') == 'Prusa-Pro-HT90-High-Temp'
    assert slug('igus® iglidur® J260') == 'igus-iglidur-J260'
