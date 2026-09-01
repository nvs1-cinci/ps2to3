"""the option schema, and deriving hardware shape from 2.x printer presets."""

from __future__ import annotations

import json
import pathlib

import pytest

from ps2to3.hardware import NOZZLE_FEATURE, PrinterVariant, Tool, VendorModel
from ps2to3.schema import Schema, SchemaUnavailable, export_schema

# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #

def test_the_shipped_schema_is_used_when_prusaslicer_is_not_installed(monkeypatch):
    """the tool has to work on a machine that has no prusaslicer 3 at all."""
    monkeypatch.setattr(Schema, 'cached_path', classmethod(lambda _c: '/nonexistent'))
    monkeypatch.setattr('ps2to3.paths.slicer_command', lambda: None)
    assert Schema.load().pool('print')['layer_height']


def test_an_explicit_schema_path_wins_over_the_shipped_one(tmp_path):
    p = tmp_path / 's.json'
    p.write_text(json.dumps({'print': {'items': [{'name': 'only_this',
                                                  'type': 'coFloat'}],
                                       'overrides': []}}), encoding='utf-8')
    s = Schema.load(str(p))
    assert list(s.pool('print')) == ['only_this']


def test_a_missing_explicit_path_is_an_error_not_a_silent_fallback(tmp_path):
    """falling back would convert against a different prusaslicer than asked."""
    with pytest.raises(SchemaUnavailable, match='no schema at'):
        Schema.load(str(tmp_path / 'gone.json'))


def test_the_print_pool_covers_the_tool_overrides_too(schema):
    """3.x lists a per-tool override of a print option in its own section.

    a print preset can carry both, so the conversion looks them up together.
    """
    assert set(schema.by_kind['tool_print']) <= set(schema.pool('print'))
    assert set(schema.by_kind['print']) <= set(schema.pool('print'))
    assert schema.pool('print')['retract_length'] is schema.by_kind['print'][
        'retract_length']


def test_nozzle_diameter_is_not_a_preset_option_in_3x(schema):
    """it is a tool feature the vendor document declares, not a printer value.

    treating it as an option is how a converted printer ends up with no tools.
    """
    assert schema.where('nozzle_diameter') == []


def test_where_reports_every_kind_an_option_belongs_to(schema):
    assert schema.where('layer_height') == ['print', 'sla_print']
    assert schema.where('retract_length') == ['print', 'tool_print', 'filament']
    assert schema.where('not_an_option') == []


def test_names_spans_every_kind(schema):
    names = schema.names()
    assert {'layer_height', 'retract_length', 'gcode_flavor'} <= names
    assert names >= set(schema.by_kind['sla_material'])


def test_exporting_without_a_slicer_says_what_to_set(monkeypatch, tmp_path):
    monkeypatch.setattr('ps2to3.paths.slicer_command', lambda: None)
    with pytest.raises(SchemaUnavailable, match='PS2TO3_SLICER'):
        export_schema(str(tmp_path / 'out.json'))


def test_a_slicer_that_writes_nothing_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr('ps2to3.schema.subprocess.run', lambda *a, **k: None)
    with pytest.raises(SchemaUnavailable, match='did not write a schema'):
        export_schema(str(tmp_path / 'out.json'), command=['prusa-slicer'])


def test_a_slicer_that_cannot_be_run_is_reported(monkeypatch, tmp_path):
    def boom(*_a, **_k):
        raise OSError('permission denied')
    monkeypatch.setattr('ps2to3.schema.subprocess.run', boom)
    with pytest.raises(SchemaUnavailable, match='could not be run'):
        export_schema(str(tmp_path / 'out.json'), command=['prusa-slicer'])


def test_the_package_and_the_packaging_state_the_same_version():
    """the zip is named from pyproject and the app reports __version__.

    two versions in one release is a support conversation nobody can win.
    """
    import re

    import ps2to3
    text = (pathlib.Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text()
    assert re.search(r'^version = "([^"]+)"', text, re.M).group(1) == ps2to3.__version__


# --------------------------------------------------------------------------- #
# hardware shape
# --------------------------------------------------------------------------- #

def variant(name='P 0.4 nozzle', **values):
    values.setdefault('printer_model', 'AC1')
    return PrinterVariant(name, values)


def model(*variants, model_id='AC1', meta=None):
    m = VendorModel(model_id, meta or {'name': 'Acme One'})
    m.variants.extend(variants)
    return m


def test_the_nozzle_comes_from_the_first_extruder():
    assert variant(nozzle_diameter='0.6').tool == Tool(0.6, False)


def test_a_high_flow_nozzle_is_a_different_tool():
    """3.x distinguishes them, and prints differ; one tool would merge them."""
    a = variant(nozzle_diameter='0.4', nozzle_high_flow='1').tool
    b = variant(nozzle_diameter='0.4', nozzle_high_flow='0').tool
    assert a != b
    assert a.tid == '0.4HF' and b.tid == '0.4'
    assert a.label == '0.4 HF'


def test_a_printer_with_no_nozzle_stated_gets_the_common_one():
    assert variant().tool.nozzle == 0.4


def test_every_nozzle_size_maps_to_a_printer_feature(schema):
    for feature in NOZZLE_FEATURE.values():
        assert feature


def test_tools_are_listed_once_in_bundle_order():
    m = model(variant('a', nozzle_diameter='0.4'),
              variant('b', nozzle_diameter='0.6'),
              variant('c', nozzle_diameter='0.4'))
    assert [t.nozzle for t in m.tools] == [0.4, 0.6]


def test_several_nozzles_mean_several_extruders():
    assert variant(nozzle_diameter='0.4,0.4,0.4,0.4').extruders == 4


def test_a_trailing_comma_does_not_invent_an_extruder():
    assert variant(nozzle_diameter='0.4,').extruders == 1


def test_a_multi_extruder_printer_is_a_tool_changer():
    m = model(variant(nozzle_diameter='0.4,0.4,0.4,0.4'))
    assert m.is_toolchanger and not m.is_mmu
    assert m.extruders == 4


def test_the_same_printer_with_one_hotend_is_an_mmu():
    """the flag is the only thing separating the two 3.x shapes."""
    m = model(variant(nozzle_diameter='0.4,0.4,0.4,0.4,0.4',
                      single_extruder_multi_material='1'))
    assert m.is_mmu and not m.is_toolchanger


def test_the_multi_material_flag_alone_does_not_make_an_mmu():
    """orca sets it on single-tool machines; 3.x then builds purge data for
    extruders that do not exist."""
    m = model(variant(nozzle_diameter='0.4', single_extruder_multi_material='1'))
    assert not m.is_mmu and not m.is_toolchanger
    assert m.extruders == 1


def test_the_tool_count_is_the_widest_variant():
    """a model's variants can disagree; the vendor doc states one shape."""
    m = model(variant('a', nozzle_diameter='0.4'),
              variant('b', nozzle_diameter='0.4,0.4'))
    assert m.extruders == 2


def test_technology_defaults_to_fff_and_is_upper_case():
    assert model(variant()).technology == 'FFF'
    assert model(variant(), meta={'technology': 'sla'}).technology == 'SLA'


def test_the_display_name_falls_back_to_the_model_id():
    assert VendorModel('AC1', {}).display == 'AC1'


def test_the_feeder_id_is_derived_from_the_model_not_the_preset_name():
    """two vendors' feeders sit in one vendor document after merging."""
    m = model(variant(), model_id='Snapmaker U1')
    assert m.feeder_id == 'snapmaker-u1-feeder'
