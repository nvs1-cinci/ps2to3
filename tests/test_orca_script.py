"""translating orca's script dialect into prusaslicer placeholders.

this exists because a converted snapmaker u1 could not print in more than one
material: `--fix-gcode` had rewritten the toolchange macro's own local variables
to `0`, and even repaired, the macro was in a dialect 3.x refuses. a refused
toolchange template stops the slice with `(38, [toolchange_gcode])` the moment a
tool change is needed, which is why single-tool prints never showed it.

the target syntax is not invented: it is what prusaslicer's own CORE One INDX
toolchange template is written in.
"""

from __future__ import annotations

import pytest

from ps2to3.orca_script import looks_like_script, translate

# every name the u1 macro reads, as 3.x would resolve them
KNOWN = frozenset((
    'travel_speed', 'layer_num', 'next_extruder', 'previous_extruder',
    'initial_extruder', 'initial_tool', 'temperature', 'first_layer_temperature',
    'filament_type', 'wipe_tower',
))


def tr(text, known=KNOWN, notes=None):
    return translate(text, known, notes.append if notes is not None else None)


# --------------------------------------------------------------------------- #
# what counts as orca's dialect
# --------------------------------------------------------------------------- #

def test_if_then_is_orcas_dialect():
    assert looks_like_script('if travel_speed < 100 then\nendif')


def test_a_string_statement_is_orcas_dialect():
    assert looks_like_script('"G91\n";')


def test_prusaslicers_own_shape_is_not(schema):
    body = '{local speed = min(travel_speed, 350.0) * 60;}\nG1 F{speed}'
    assert not looks_like_script(body)


def test_a_quoted_comparison_is_not():
    assert not looks_like_script('{if filament_type[0] == "PLA"}M104{endif}')


# --------------------------------------------------------------------------- #
# statements
# --------------------------------------------------------------------------- #

def test_a_declaration_becomes_a_local_block():
    assert tr('{local speed = 350.0;\n"M400\n";}') == '{local speed = 350.0}M400\n'


def test_an_assignment_to_a_declared_local_is_kept():
    got = tr('{local speed = 1; speed = travel_speed; "G1 F" + speed + "\n";}')
    assert got == '{local speed = 1}{speed = travel_speed}G1 F{speed}\n'


def test_an_assignment_to_orcas_own_runtime_state_is_dropped_and_named():
    """`position[2] = position[2] + 2.0` is in the u1 macro.

    prusaslicer has no `position`, and an unknown name makes it refuse the whole
    template, so the statement goes and the note says so.
    """
    notes = []
    got = tr('{position[2] = position[2] + 2.0;\nlocal x = 1;\n"M400\n";}',
             notes=notes)
    assert got == '{local x = 1}M400\n'
    assert any("assigns to 'position'" in n for n in notes)


def test_a_string_statement_becomes_text_outside_the_block():
    assert tr('{"G91\nG1 Z1.5\n";}') == 'G91\nG1 Z1.5\n'


def test_a_concatenation_becomes_text_with_interpolation():
    assert tr('{"G1 F" + travel_speed + "\n";}') == 'G1 F{travel_speed}\n'


def test_an_expression_keeps_its_parentheses():
    got = tr('{local s = 1;\n"G1 F" + (s * 60) + "\n";}')
    assert got == '{local s = 1}G1 F{(s * 60)}\n'


def test_an_indexed_read_survives():
    got = tr('{"M109 S" + temperature[next_extruder] + "\n";}')
    assert got == 'M109 S{temperature[next_extruder]}\n'


def test_a_semicolon_inside_a_string_does_not_end_the_statement():
    assert tr('{"; a comment; still text\n";}') == '; a comment; still text\n'


# --------------------------------------------------------------------------- #
# control flow, turned inside out
# --------------------------------------------------------------------------- #

def test_if_then_endif_becomes_a_placeholder_conditional():
    got = tr('{if layer_num == 0 then\n"M17\n";\nendif}')
    assert got == '{if layer_num == 0}M17\n{endif}'


def test_else_becomes_else():
    got = tr('{if layer_num == 0 then "A\n"; else "B\n"; endif}')
    assert got == '{if layer_num == 0}A\n{else}B\n{endif}'


def test_an_empty_else_is_not_emitted():
    """the u1 macro has one, and `{else}{endif}` is noise in the g-code."""
    got = tr('{if filament_type[next_extruder] == "PVA" then "X\n"; else endif}')
    assert got == '{if filament_type[next_extruder] == "PVA"}X\n{endif}'


def test_elsif_becomes_elsif():
    got = tr('{if layer_num == 0 then "A\n"; elsif layer_num == 1 then "B\n"; endif}')
    assert got == '{if layer_num == 0}A\n{elsif layer_num == 1}B\n{endif}'


def test_nested_conditionals_nest():
    got = tr('{if wipe_tower then if layer_num == 0 then "A\n"; endif endif}')
    assert got == '{if wipe_tower}{if layer_num == 0}A\n{endif}{endif}'


def test_a_condition_with_and_or_not_passes_through():
    got = tr('{if wipe_tower and not((layer_num < 0) and '
             '(next_extruder == initial_tool)) then "A\n"; endif}')
    assert got.startswith('{if wipe_tower and not((layer_num < 0) and '
                          '(next_extruder == initial_tool))}')


# --------------------------------------------------------------------------- #
# refusals: a half-translated macro drives a tool head, so it is never shipped
# --------------------------------------------------------------------------- #

def test_an_unresolvable_name_refuses_the_whole_translation():
    assert tr('{"X" + chamber_type + "\n";}') is None


def test_an_if_without_endif_refuses():
    assert tr('{if layer_num == 0 then "A\n";}') is None


def test_an_if_without_then_refuses():
    assert tr('{if layer_num == 0 "A\n"; endif}') is None


def test_a_statement_without_a_terminator_refuses():
    assert tr('{"M400\n";\nlocal x = 1}') is None


def test_a_block_that_needs_no_translation_is_not_second_guessed():
    """`{local x = 1}` is already what prusaslicer writes."""
    assert tr('{local x = 1}\nG1 F{x}') == '{local x = 1}\nG1 F{x}'


def test_an_unterminated_string_refuses():
    assert tr('{"G91\n;}') is None


def test_a_brace_in_emitted_text_refuses():
    """it would be read as a placeholder rather than printed."""
    assert tr('{"M117 {tricky}\n";}') is None


def test_text_outside_a_block_is_copied_through():
    got = tr('; header\n{"M400\n";}\n; footer\n')
    assert got == '; header\nM400\n\n; footer\n'


def test_a_block_already_in_prusaslicers_form_is_left_alone():
    body = '{local speed = min(travel_speed, 350) * 60}\nG1 F{speed}'
    assert tr(body) == body


# --------------------------------------------------------------------------- #
# the real thing
# --------------------------------------------------------------------------- #

U1_TOOLCHANGE = '''{
local max_speed_toolchange = 350.0;
local wait_for_extruder_temp = true;
position[2] = position[2] + 2.0;
local speed_toolchange = max_speed_toolchange;
if travel_speed < max_speed_toolchange then
      speed_toolchange = travel_speed;
endif
"G91
G1 Z1.5 F1800
G90
";
"G1 F" + (speed_toolchange * 60) + "
";
if wait_for_extruder_temp and not((layer_num < 0) and (next_extruder == initial_tool)) then
      "; " + layer_num + "
";
      if layer_num == 0 then
            "M109 S" + first_layer_temperature[next_extruder] + " T" + next_extruder + "
";
      else
            "M109 S" + temperature[next_extruder] + " T" + next_extruder + "
";
      endif
endif
"M400" + "
";
"T" + next_extruder + "
";
if previous_extruder != next_extruder and initial_extruder != next_extruder then
"SM_PRINT_PREEXTRUDE_FILAMENT INDEX=" + next_extruder + "
";
endif
"G90
";
}'''


@pytest.fixture
def u1():
    notes = []
    got = translate(U1_TOOLCHANGE, KNOWN, notes.append)
    assert got is not None, 'the u1 toolchange macro has to translate'
    return got, notes


def test_the_u1_macro_still_changes_tool(u1):
    """without the T command the printer never switches, and prusaslicer does
    not add one of its own when a toolchange template is present."""
    got, _ = u1
    assert 'T{next_extruder}\n' in got


def test_the_u1_macro_keeps_the_vendors_own_lines(u1):
    got, _ = u1
    for line in ('G91', 'G1 Z1.5 F1800', 'M400',
                 'SM_PRINT_PREEXTRUDE_FILAMENT INDEX={next_extruder}'):
        assert line in got


def test_the_u1_macro_keeps_its_preheat_conditional(u1):
    got, _ = u1
    assert '{if layer_num == 0}M109 S{first_layer_temperature[next_extruder]}' in got
    assert '{else}M109 S{temperature[next_extruder]}' in got


def test_the_u1_macro_has_nothing_scripty_left(u1):
    got, _ = u1
    assert not looks_like_script(got)


def test_the_u1_macro_reports_the_one_statement_it_could_not_carry(u1):
    _got, notes = u1
    assert [n for n in notes if 'position' in n]
