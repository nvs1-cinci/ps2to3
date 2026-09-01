"""fixtures shared by the suite.

nothing here reads the machine's own prusaslicer install. every source a test
converts is built in a tmp directory, so the suite gives the same answer on any
machine.
"""

from __future__ import annotations

import textwrap

import pytest

from ps2to3.schema import Schema


@pytest.fixture(scope='session')
def schema():
    """the real shipped schema, so type handling is tested against real types."""
    return Schema.load(Schema.shipped_path())


@pytest.fixture
def write(tmp_path):
    """write a dedented file under tmp_path and return its path."""
    def _write(name, body):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body).lstrip('\n'), encoding='utf-8')
        return str(path)
    return _write


@pytest.fixture
def vendor_ini(write):
    """a minimal but complete 2.x vendor bundle: one printer, print, filament."""
    return write('Acme.ini', """
        [vendor]
        name = Acme
        repo_id = acme-fff
        config_version = 1.0.0

        [printer_model:AC1]
        name = Acme One
        variants = 0.4;0.6
        technology = FFF
        family = Acme
        default_materials = Acme PLA @AC1 0.4

        [printer:*common*]
        printer_model = AC1
        printer_technology = FFF
        gcode_flavor = marlin2
        nozzle_diameter = 0.4
        printer_variant = 0.4
        bed_shape = 0x0,200x0,200x200,0x200
        max_print_height = 210
        retract_length = 1.1
        retract_speed = 40
        min_layer_height = 0.07
        max_layer_height = 0.3
        thumbnails = 32x32
        thumbnails_format = PNG
        start_gcode = G28 ; home\\nM104 S[first_layer_temperature]
        end_gcode = M104 S0\\nM84
        printer_notes = PRINTER_VENDOR_ACME\\nPRINTER_MODEL_AC1

        [printer:Acme One 0.4 nozzle]
        inherits = *common*

        [printer:Acme One 0.6 nozzle]
        inherits = *common*
        nozzle_diameter = 0.6
        printer_variant = 0.6
        max_layer_height = 0.4

        [print:*common*]
        layer_height = 0.2
        first_layer_height = 0.2
        perimeters = 2
        fill_density = 15%
        support_material = 0
        support_material_auto = 0
        avoid_crossing_perimeters_max_detour = 40%
        gcode_substitutions = ";profile_gcode";"SET_VELOCITY_LIMIT ACCEL_TO_DECEL=4000";;

        [print:0.20mm @AC1 0.4]
        inherits = *common*
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_AC1.*/ and nozzle_diameter[0]==0.4

        [print:0.30mm @AC1 0.6]
        inherits = *common*
        layer_height = 0.3
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_AC1.*/ and nozzle_diameter[0]==0.6

        [filament:*common*]
        filament_type = PLA
        filament_diameter = 1.75
        temperature = 210
        first_layer_temperature = 215
        bed_temperature = 60
        first_layer_bed_temperature = 60
        filament_cost =
        start_filament_gcode = "; filament start\\nM900 K0\\n"

        [filament:Acme PLA @AC1 0.4]
        inherits = *common*
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_AC1.*/ and nozzle_diameter[0]==0.4
        """)
