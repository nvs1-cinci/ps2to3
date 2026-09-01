"""the 2.x compatibility expression evaluator."""

from __future__ import annotations

import pytest

from ps2to3.conditions import ConditionEvaluator

PRINTER = {
    'printer_notes': 'PRINTER_VENDOR_ACME\\nPRINTER_MODEL_AC1\\nNO_TEMPLATES',
    'nozzle_diameter': '0.4',
    'nozzle_high_flow': '1',
    'max_print_height': '210',
    'single_extruder_multi_material': '0',
}


def ev(values=None):
    return ConditionEvaluator(values if values is not None else PRINTER)


@pytest.mark.parametrize('expr', [
    '',
    '   ',
])
def test_no_condition_matches_everything(expr):
    assert ev().evaluate(expr) is True


def test_regex_over_printer_notes():
    assert ev().evaluate('printer_notes=~/.*PRINTER_MODEL_AC1.*/')
    assert not ev().evaluate('printer_notes=~/.*PRINTER_MODEL_ZZ.*/')


def test_negated_regex():
    assert ev().evaluate('printer_notes!~/.*TEMPLATES_ONLY.*/')
    assert not ev().evaluate('printer_notes!~/.*NO_TEMPLATES.*/')


def test_indexed_numeric_comparison():
    assert ev().evaluate('nozzle_diameter[0]==0.4')
    assert not ev().evaluate('nozzle_diameter[0]==0.6')


def test_bare_flag_is_truthy():
    assert ev().evaluate('nozzle_high_flow[0]')
    assert not ev().evaluate('! nozzle_high_flow[0]')


def test_negation_without_a_space():
    """positron3d writes `!nozzle_high_flow[0]`, with no space."""
    assert not ev().evaluate('!nozzle_high_flow[0]')


def test_word_operators():
    assert ev().evaluate('nozzle_diameter[0]==0.4 and nozzle_high_flow[0]')
    assert ev().evaluate('nozzle_diameter[0]==0.6 or nozzle_high_flow[0]')


def test_c_style_operators():
    """prusaresearch's own bundle uses && and ||."""
    assert ev().evaluate('nozzle_diameter[0]==0.4 && nozzle_high_flow[0]')
    assert ev().evaluate('nozzle_diameter[0]==0.6 || nozzle_high_flow[0]')


def test_parentheses_and_mixed_operators():
    expr = ('(printer_notes=~/.*AC1.*/ and nozzle_diameter[0]==0.4) '
            'or nozzle_diameter[0]==0.8')
    assert ev().evaluate(expr)


def test_an_option_the_printer_never_sets_is_falsy_not_an_error():
    """a condition may name an option this printer has no value for."""
    assert not ev().evaluate('some_option_we_never_set')


def test_comparing_an_unset_option_to_a_number_does_not_raise():
    """everything in a 2.x ini is text, so an unset option meets a float."""
    assert not ev().evaluate('never_set > 0.1')


def test_string_equality_against_a_quoted_literal():
    assert ev({'printer_model': 'AC1'}).evaluate('printer_model=="AC1"')
    assert not ev({'printer_model': 'AC1'}).evaluate('printer_model=="AC2"')


def test_missing_options_are_recorded_for_reporting():
    missing = set()
    ConditionEvaluator(PRINTER, missing).evaluate('mystery_option[0]==1')
    assert 'mystery_option' in missing


def test_unparseable_condition_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        ev().evaluate('nozzle_diameter[0] ?? 0.4')
