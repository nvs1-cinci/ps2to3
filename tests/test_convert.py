"""converting a whole source, and the shapes 3.x insists on.

every assertion here is something 3.0.0-alpha10 either rejects loudly or, worse,
accepts and then silently produces no printers from.
"""

from __future__ import annotations

import base64
import glob
import os
import uuid
import zipfile

import pytest
import yaml

from ps2to3.bundle import open_bundle
from ps2to3.convert import Conversion
from ps2to3.files import read_json


@pytest.fixture
def converted(vendor_ini, schema, tmp_path):
    bundle = open_bundle(vendor_ini, schema=schema)
    conv = Conversion(bundle, schema, vendor_id='Acme')
    out = str(tmp_path / 'build')
    info = conv.emit(out)
    return conv, info, out


def docs(path):
    with open(path, encoding='utf-8') as fh:
        return [d for d in yaml.safe_load_all(fh) if isinstance(d, dict)]


def vendor_docs(out, vendor_id='Acme', version='1.0.0'):
    return docs(os.path.join(out, vendor_id, version, 'vendor.yaml'))


def one(out, pattern, vendor_id='Acme', version='1.0.0'):
    found = glob.glob(os.path.join(out, vendor_id, version, pattern))
    assert len(found) == 1, f'{pattern} matched {found}'
    return found[0]


# --------------------------------------------------------------------------- #
# what came out
# --------------------------------------------------------------------------- #

def test_counts_match_the_source(converted):
    _conv, info, _out = converted
    assert info['models'] == 1
    assert info['print_presets'] == 2
    assert info['filament_presets'] == 1


def test_every_preset_kind_is_written(converted):
    _conv, _info, out = converted
    names = {os.path.basename(p) for p in
             glob.glob(os.path.join(out, 'Acme', '1.0.0', '*.yaml'))}
    assert 'vendor.yaml' in names
    assert any(n.startswith('preset-printer-') for n in names)
    assert any(n.startswith('preset-print-') for n in names)
    assert any(n.startswith('preset-tool-') for n in names)
    assert any(n.startswith('preset-filament-') for n in names)


# --------------------------------------------------------------------------- #
# shapes 3.x requires
# --------------------------------------------------------------------------- #

def test_repository_manifest_is_an_object_not_an_array(converted):
    """the data directory's RepositoryManifest.json is an array; a repo's is not.

    getting it wrong makes --preset-update-add-local fail with no message.
    """
    _conv, _info, out = converted
    got = read_json(os.path.join(out, 'manifest.json'))
    assert isinstance(got, dict)
    assert got['version'] == 2
    assert got['id']


def test_version_manifest_lists_every_file_but_itself(converted):
    _conv, _info, out = converted
    vdir = os.path.join(out, 'Acme', '1.0.0')
    listed = {e['filename'] for e in
              read_json(os.path.join(vdir, 'manifest.json'))}
    on_disk = set()
    for root, _dirs, files in os.walk(vdir):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), vdir).replace(os.sep, '/')
            on_disk.add(rel)
    assert listed == on_disk - {'manifest.json'}


def test_index_archive_holds_the_vendor_idx(converted):
    _conv, _info, out = converted
    with zipfile.ZipFile(os.path.join(out, 'vendor_indices.zip')) as z:
        assert z.namelist() == ['Acme.idx']
        assert b'min_slic3r_version' in z.read('Acme.idx')


def test_every_preset_id_is_a_base64_uuid4(converted):
    """an id that is not a uuid is accepted by the reader and then ignored."""
    _conv, _info, out = converted
    seen = 0
    for path in glob.glob(os.path.join(out, 'Acme', '1.0.0', 'preset-*.yaml')):
        for doc in docs(path):
            for node in [doc] + list(doc.get('variants') or []):
                raw = node.get('id')
                if isinstance(raw, str) and len(raw) == 22 and '*' not in raw:
                    parsed = uuid.UUID(bytes=base64.b64decode(raw + '=='))
                    assert parsed.version == 4
                    seen += 1
    assert seen, 'no generated ids found to check'


def test_one_tool_print_variant_per_printer_model(vendor_ini, schema, tmp_path):
    """a single variant whose condition matches several models resolves for one.

    picking any other model then dies in preset evaluation.
    """
    bundle = open_bundle(vendor_ini, schema=schema)
    conv = Conversion(bundle, schema, vendor_id='Acme')
    out = str(tmp_path / 'b')
    conv.emit(out)
    doc = docs(one(out, 'preset-tool-*.yaml'))[0]
    models = [m.id for m in conv.models.values()]
    conditions = [v['condition'] for v in doc['variants']]
    assert len(doc['variants']) == len(models)
    for m in models:
        assert any(f'"{m}"' in c for c in conditions)


def test_print_presets_always_name_their_printer(converted):
    """a preset compatible with everything in its own bundle needs no condition.

    converted bundles share one 3.x vendor, so an unconditioned preset would be
    offered for every other vendor's printers too.
    """
    _conv, _info, out = converted
    for doc in docs(one(out, 'preset-print-*.yaml')):
        assert 'printer.model ==' in doc['condition']


def test_nozzle_specific_presets_carry_a_tool_condition(converted):
    _conv, _info, out = converted
    by_name = {d['name']: d for d in docs(one(out, 'preset-print-*.yaml'))}
    assert 'tool.nozzle_diameter == 0.4' in by_name['0.20mm @AC1 0.4']['condition']
    assert 'tool.nozzle_diameter == 0.6' in by_name['0.30mm @AC1 0.6']['condition']


def test_printer_level_retraction_moves_onto_the_print_preset(converted):
    """3.x keeps retraction on the print preset, 2.x kept it on the printer."""
    _conv, _info, out = converted
    doc = docs(one(out, 'preset-print-*.yaml'))[0]
    assert doc['values']['retract_length'] == 1.1
    assert doc['values']['max_layer_height'] in (0.3, 0.4)


def test_vendor_declares_a_tool_per_nozzle(converted):
    _conv, _info, out = converted
    tools = [d for d in vendor_docs(out) if d.get('kind') == 'tool']
    assert {d['features']['nozzle_diameter']['default'] for d in tools} == {0.4, 0.6}


def test_vendor_tool_ids_are_namespaced(converted):
    """merging puts these beside prusa's own tools, whose ids would collide.

    prusa also declares no 0.2 nozzle, so borrowing its tools is not enough.
    """
    _conv, _info, out = converted
    tools = [d for d in vendor_docs(out) if d.get('kind') == 'tool']
    assert all(str(d['id']).startswith('acme-') for d in tools)


def test_printer_config_points_at_a_declared_tool(converted):
    _conv, _info, out = converted
    ids = {str(d['id']) for d in vendor_docs(out) if d.get('kind') == 'tool'}
    for cfg in [d for d in vendor_docs(out) if d.get('kind') == 'printer_config']:
        assert cfg['tools'][0]['tool'] in ids


def test_single_tool_printer_turns_multi_material_off(converted):
    """single_extruder_multi_material means one hotend fed from several sources.

    orca sets it on every printer; 3.x then builds purge data for extruders that
    do not exist.
    """
    _conv, _info, out = converted
    printer = docs(one(out, 'preset-printer-*.yaml'))[0]
    assert printer['variants'][0]['values']['single_extruder_multi_material'] is False


# --------------------------------------------------------------------------- #
# multi-material
# --------------------------------------------------------------------------- #

@pytest.fixture
def multi_tool_ini(write):
    return write('Multi.ini', """
        [vendor]
        name = Multi
        repo_id = multi-fff

        [printer_model:MX]
        name = Multi X
        variants = 0.4
        technology = FFF

        [printer:Multi X 0.4 nozzle]
        printer_model = MX
        printer_technology = FFF
        gcode_flavor = marlin2
        nozzle_diameter = 0.4,0.4,0.4,0.4
        printer_variant = 0.4
        bed_shape = 0x0,200x0,200x200,0x200
        max_print_height = 200
        single_extruder_multi_material = 0
        printer_notes = PRINTER_MODEL_MX

        [print:0.20mm @MX]
        layer_height = 0.2
        first_layer_height = 0.2
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_MX.*/

        [filament:Multi PLA @MX]
        filament_type = PLA
        filament_diameter = 1.75
        temperature = 210
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_MX.*/
        """)


@pytest.fixture
def mmu_ini(write):
    return write('Mmu.ini', """
        [vendor]
        name = Mmu
        repo_id = mmu-fff

        [printer_model:MM]
        name = Mmu One
        variants = 0.4
        technology = FFF

        [printer:Mmu One 0.4 nozzle]
        printer_model = MM
        printer_technology = FFF
        gcode_flavor = marlin2
        nozzle_diameter = 0.4,0.4,0.4,0.4,0.4
        printer_variant = 0.4
        single_extruder_multi_material = 1
        bed_shape = 0x0,200x0,200x200,0x200
        max_print_height = 200
        printer_notes = PRINTER_MODEL_MM

        [print:0.20mm @MM]
        layer_height = 0.2
        first_layer_height = 0.2
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_MM.*/

        [filament:Mmu PLA @MM]
        filament_type = PLA
        filament_diameter = 1.75
        temperature = 210
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_MM.*/
        """)


def test_tool_changer_gets_a_tool_count(multi_tool_ini, schema, tmp_path):
    bundle = open_bundle(multi_tool_ini, schema=schema)
    conv = Conversion(bundle, schema, vendor_id='Multi')
    out = str(tmp_path / 'b')
    conv.emit(out)
    model = next(iter(conv.models.values()))
    assert model.is_toolchanger and model.extruders == 4

    cfg = [d for d in vendor_docs(out, 'Multi') if d.get('kind') == 'printer_config'][0]
    assert cfg['tool_count'] == 4
    assert 'feeders' not in cfg
    printer = [d for d in vendor_docs(out, 'Multi')
               if d.get('kind') == 'printer' and 'model' in d][0]
    assert printer['features']['multi_extruder']['default'] is True


def test_tool_changer_gets_one_extruder_offset_per_tool(multi_tool_ini, schema,
                                                       tmp_path):
    """3.x rejects a printer whose offsets are shorter than its tool count.

    2.x often leaves the option unset because its default filled the gap.
    """
    bundle = open_bundle(multi_tool_ini, schema=schema)
    conv = Conversion(bundle, schema, vendor_id='Multi')
    out = str(tmp_path / 'b')
    conv.emit(out)
    printer = docs(one(out, 'preset-printer-*.yaml', 'Multi'))[0]
    assert printer['variants'][0]['values']['extruder_offset'] == ['0x0'] * 4


def test_mmu_becomes_a_feeder_not_a_tool_changer(mmu_ini, schema, tmp_path):
    bundle = open_bundle(mmu_ini, schema=schema)
    conv = Conversion(bundle, schema, vendor_id='Mmu')
    out = str(tmp_path / 'b')
    conv.emit(out)
    model = next(iter(conv.models.values()))
    assert model.is_mmu and not model.is_toolchanger

    vdocs = vendor_docs(out, 'Mmu')
    feeder = [d for d in vdocs if d.get('kind') == 'feeder']
    assert len(feeder) == 1
    assert feeder[0]['feeder_type'] == 'mmu'
    assert feeder[0]['slot_count'] == 5

    cfg = [d for d in vdocs if d.get('kind') == 'printer_config'][0]
    assert cfg['feeders'][0]['feeder'] == feeder[0]['id']
    assert 'tool_count' not in cfg

    printer = docs(one(out, 'preset-printer-*.yaml', 'Mmu'))[0]
    assert printer['variants'][0]['values']['single_extruder_multi_material'] is True


# --------------------------------------------------------------------------- #
# assets
# --------------------------------------------------------------------------- #

def test_asset_a_source_names_but_never_shipped_is_dropped(write, schema, tmp_path):
    """the 2.x positron3d bundle names bedmodel_prusawire.stl and omits it.

    3.x is unhappy loading a missing asset, and the ui was the surface that
    showed it.
    """
    ini = write('Gap.ini', """
        [vendor]
        name = Gap
        repo_id = gap-fff

        [printer_model:GP]
        name = Gap One
        variants = 0.4
        technology = FFF
        bed_model = missing_bed.stl
        bed_texture = present.svg

        [printer:Gap One 0.4 nozzle]
        printer_model = GP
        printer_technology = FFF
        nozzle_diameter = 0.4
        bed_shape = 0x0,100x0,100x100,0x100
        max_print_height = 100
        printer_notes = PRINTER_MODEL_GP

        [print:0.20mm @GP]
        layer_height = 0.2
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_GP.*/

        [filament:Gap PLA @GP]
        filament_type = PLA
        temperature = 210
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_GP.*/
        """)
    assets = tmp_path / 'assets'
    assets.mkdir()
    (assets / 'present.svg').write_text('<svg/>', encoding='utf-8')

    bundle = open_bundle(ini, schema=schema)
    conv = Conversion(bundle, schema, vendor_id='Gap', assets_dir=str(assets))
    out = str(tmp_path / 'b')
    conv.emit(out)

    printer = [d for d in vendor_docs(out, 'Gap')
               if d.get('kind') == 'printer' and 'model' in d][0]
    assert 'bed_model' not in printer.get('visual', {})
    assert printer['visual']['bed_texture'] == 'present.svg'
    assert any('not among the assets' in m for m in conv.conv.notes)


def test_visual_override_supplies_what_a_config_bundle_cannot_name(write, schema,
                                                                  tmp_path):
    ini = write('Cfg.ini', """
        [printer:Cfg 0.4 nozzle]
        printer_model = CFG
        printer_technology = FFF
        nozzle_diameter = 0.4
        bed_shape = 0x0,100x0,100x100,0x100
        max_print_height = 100

        [print:Cfg fine]
        layer_height = 0.12

        [filament:Cfg PLA]
        filament_type = PLA
        temperature = 210
        """)
    assets = tmp_path / 'assets'
    assets.mkdir()
    (assets / 'plate.stl').write_bytes(b'solid\n')

    bundle = open_bundle(ini, schema=schema)
    conv = Conversion(bundle, schema, vendor_id='Cfg', assets_dir=str(assets),
                      visual={'bed_model': 'plate.stl'})
    out = str(tmp_path / 'b')
    conv.emit(out)
    printer = [d for d in vendor_docs(out, 'Cfg')
               if d.get('kind') == 'printer' and 'model' in d][0]
    assert printer['visual']['bed_model'] == 'plate.stl'


def test_a_preset_matching_no_printer_is_skipped_and_named(write, schema, tmp_path):
    ini = write('Dead.ini', """
        [vendor]
        name = Dead
        repo_id = dead-fff

        [printer_model:DD]
        name = Dead One
        variants = 0.4
        technology = FFF

        [printer:Dead One 0.4 nozzle]
        printer_model = DD
        printer_technology = FFF
        nozzle_diameter = 0.4
        bed_shape = 0x0,100x0,100x100,0x100
        max_print_height = 100
        printer_notes = PRINTER_MODEL_DD

        [print:for a printer that left]
        layer_height = 0.2
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_GONE.*/

        [filament:Dead PLA @DD]
        filament_type = PLA
        temperature = 210
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_DD.*/
        """)
    bundle = open_bundle(ini, schema=schema)
    conv = Conversion(bundle, schema, vendor_id='Dead')
    info = conv.emit(str(tmp_path / 'b'))
    assert info['print_presets'] == 0
    assert ('print', 'for a printer that left') in conv.skipped


def test_verify_covers_the_array_valued_options():
    """no prusa 3.x preset sets either, so a conversion is the only thing that
    can get their shape wrong, and nothing else here would notice."""
    from ps2to3.verify import COMPARED_KEYS
    assert 'gcode_substitutions' in COMPARED_KEYS
    assert 'post_process' in COMPARED_KEYS


def test_a_substitution_row_keeps_its_four_items(vendor_ini, schema, tmp_path):
    """2.x packs four strings per row, and 3.0.0-alpha10 read a converted value
    back through `--save` as the same four-item row it was given."""
    bundle = open_bundle(vendor_ini, schema=schema)
    conv = Conversion(bundle, schema, vendor_id='Acme')
    out = str(tmp_path / 'b')
    conv.emit(out)
    doc = docs(one(out, 'preset-print-*.yaml'))[0]
    assert doc['values']['gcode_substitutions'] == [
        ';profile_gcode', 'SET_VELOCITY_LIMIT ACCEL_TO_DECEL=4000', '', '']
