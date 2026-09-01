"""the command line, end to end.

`convert` then `verify` then `install` is the whole workflow, so these run it.
"""

from __future__ import annotations

import os

import pytest

from ps2to3 import cli, install
from ps2to3.files import read as read_text
from ps2to3.files import read_json
from ps2to3.files import write as write_text


def run(capsys, *argv):
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


# --------------------------------------------------------------------------- #
# convert
# --------------------------------------------------------------------------- #

def test_convert_reports_what_it_produced(capsys, vendor_ini, tmp_path):
    code, out = run(capsys, 'convert', vendor_ini, '-o', str(tmp_path / 'b'),
                    '--vendor-id', 'Acme')
    assert code == 0
    assert 'printer models    1' in out
    assert 'Acme One - single tool, nozzles 0.4, 0.6' in out
    assert 'print presets     2' in out


def test_convert_writes_a_report_that_names_the_hardware(capsys, vendor_ini, tmp_path):
    report = tmp_path / 'r.json'
    run(capsys, 'convert', vendor_ini, '-o', str(tmp_path / 'b'),
        '--vendor-id', 'Acme', '--report', str(report))
    got = read_json(report)
    assert got['vendor_id'] == 'Acme'
    assert got['models']['AC1']['tools'] == ['0.4', '0.6']
    assert got['models']['AC1']['shape'] == 'single tool'


def test_convert_names_the_multi_material_shape_it_derived(capsys, write, tmp_path):
    ini = write('T.ini', """
        [printer_model:TX]
        name = Tool X
        variants = 0.4

        [printer:Tool X 0.4 nozzle]
        printer_model = TX
        nozzle_diameter = 0.4,0.4,0.4,0.4
        bed_shape = 0x0,100x0,100x100,0x100
        max_print_height = 100

        [print:fine]
        layer_height = 0.2

        [filament:PLA]
        filament_type = PLA
        temperature = 210
        """)
    _code, out = run(capsys, 'convert', ini, '-o', str(tmp_path / 'b'),
                     '--vendor-id', 'Tool')
    assert '4-tool changer' in out


def test_convert_lists_the_conversion_notes(capsys, write, tmp_path):
    ini = write('N.ini', """
        [printer:P 0.4 nozzle]
        printer_model = P
        nozzle_diameter = 0.4
        bed_shape = 0x0,100x0,100x100,0x100
        max_print_height = 100
        wipe_tower_rotation_angle = 0

        [print:fine]
        layer_height = 0.2

        [filament:PLA]
        filament_type = PLA
        temperature = 210
        """)
    _code, out = run(capsys, 'convert', ini, '-o', str(tmp_path / 'b'),
                     '--vendor-id', 'N')
    assert 'conversion note(s)' in out
    assert 'wipe_tower_rotation_angle' in out


def test_convert_names_presets_it_had_to_skip(capsys, write, tmp_path):
    ini = write('S.ini', """
        [printer:P 0.4 nozzle]
        printer_model = P
        nozzle_diameter = 0.4
        printer_notes = PRINTER_MODEL_P
        bed_shape = 0x0,100x0,100x100,0x100
        max_print_height = 100

        [print:for another printer]
        layer_height = 0.2
        compatible_printers_condition = printer_notes=~/.*PRINTER_MODEL_Q.*/

        [filament:PLA]
        filament_type = PLA
        temperature = 210
        """)
    _code, out = run(capsys, 'convert', ini, '-o', str(tmp_path / 'b'),
                     '--vendor-id', 'S')
    assert '1 preset(s) skipped' in out
    assert 'print: for another printer' in out


def test_a_missing_schema_is_a_message_not_a_traceback(capsys, vendor_ini, tmp_path):
    with pytest.raises(SystemExit, match='no schema at'):
        run(capsys, 'convert', vendor_ini, '-o', str(tmp_path / 'b'),
            '--schema', str(tmp_path / 'gone.json'))


def test_a_source_that_is_not_there_is_a_message_not_a_traceback(capsys, tmp_path):
    with pytest.raises(SystemExit, match='does not exist'):
        run(capsys, 'convert', str(tmp_path / 'nothing.ini'),
            '-o', str(tmp_path / 'b'))


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #

def test_verify_finds_no_problems_in_a_fresh_conversion(capsys, vendor_ini, tmp_path):
    build = str(tmp_path / 'b')
    run(capsys, 'convert', vendor_ini, '-o', build, '--vendor-id', 'Acme')
    code, out = run(capsys, 'verify', vendor_ini, build)
    assert code == 0
    assert '0 problem(s)' in out


def test_verify_notices_a_value_that_did_not_survive(capsys, vendor_ini, tmp_path):
    """the conversion is checked against the source, not against itself."""
    build = str(tmp_path / 'b')
    run(capsys, 'convert', vendor_ini, '-o', build, '--vendor-id', 'Acme')
    import glob
    target, = glob.glob(os.path.join(build, 'Acme', '1.0.0', 'preset-printer-*.yaml'))
    text = read_text(target).replace('G28 ; home', 'G28 ; tampered')
    write_text(target, text)
    code, out = run(capsys, 'verify', vendor_ini, build)
    assert code == 1
    assert 'problem(s)' in out and '0 problem(s)' not in out


# --------------------------------------------------------------------------- #
# install
# --------------------------------------------------------------------------- #

@pytest.fixture
def installed(capsys, vendor_ini, tmp_path):
    build = str(tmp_path / 'b')
    run(capsys, 'convert', vendor_ini, '-o', build, '--vendor-id', 'Acme')
    dd = tmp_path / 'dd'
    vendor = dd / 'presets' / 'local' / install.MERGE_REPO / 'PrusaResearch'
    vendor.mkdir(parents=True)
    (vendor / 'vendor.yaml').write_text('kind: vendor\nid: PrusaResearch\n',
                                        encoding='utf-8')
    return build, str(dd)


def test_install_states_the_warning_unless_it_is_waived(capsys, installed):
    build, dd = installed
    _code, out = run(capsys, 'install', build, '--datadir', dd)
    assert 'do not report it to' in out
    assert 'merged Acme into' in out

    _code, out = run(capsys, 'install', build, '--datadir', dd, '-y')
    assert 'do not report it to' not in out


def test_install_says_a_preset_update_will_undo_it(capsys, installed):
    """it did, once, and nothing said it would."""
    build, dd = installed
    _code, out = run(capsys, 'install', build, '--datadir', dd, '-y')
    assert 'ps2to3 restore' in out


def test_the_vendor_id_is_taken_from_the_build_when_not_given(capsys, installed):
    build, dd = installed
    _code, out = run(capsys, 'install', build, '--datadir', dd, '-y')
    assert 'merged Acme' in out


def test_uninstall_with_no_vendor_lists_what_is_installed(capsys, installed):
    build, dd = installed
    run(capsys, 'install', build, '--datadir', dd, '-y')
    _code, out = run(capsys, 'uninstall', '--datadir', dd)
    assert 'Acme' in out and 'installed' in out


def test_uninstall_removes_the_named_vendor(capsys, installed):
    build, dd = installed
    run(capsys, 'install', build, '--datadir', dd, '-y')
    _code, out = run(capsys, 'uninstall', 'Acme', '--datadir', dd)
    assert 'removed Acme' in out
    _code, out = run(capsys, 'uninstall', '--datadir', dd)
    assert 'nothing installed by ps2to3' in out


def test_restore_says_so_when_there_is_nothing_to_do(capsys, installed):
    build, dd = installed
    run(capsys, 'install', build, '--datadir', dd, '-y')
    _code, out = run(capsys, 'restore', '--datadir', dd)
    assert 'already installed' in out


def test_no_data_directory_lists_where_it_looked(capsys, installed, monkeypatch):
    """the message has to be actionable on a machine this tool has never seen."""
    monkeypatch.setattr(cli.paths, 'data_dirs', lambda: [])
    build, _dd = installed
    with pytest.raises(SystemExit, match='PS2TO3_DATADIR'):
        run(capsys, 'install', build)


def test_a_datadir_without_the_prusa_vendor_is_not_chosen(capsys, installed,
                                                          monkeypatch, tmp_path):
    from ps2to3.paths import DataDir
    empty = DataDir(path=str(tmp_path / 'empty'), origin='test', exists=True,
                    has_presets=True, has_prusa_vendor=False)
    monkeypatch.setattr(cli.paths, 'data_dirs', lambda: [empty])
    build, _dd = installed
    with pytest.raises(SystemExit, match='no PrusaResearch vendor'):
        run(capsys, 'install', build)


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #

def test_paths_reports_the_locations_without_needing_prusaslicer(capsys):
    code, out = run(capsys, 'paths')
    assert code == 0
    for line in ('platform', 'prusaslicer 3', 'schema shipped', 'data directories',
                 '2.x bundles'):
        assert line in out


def test_paths_names_nobodys_home_directory_in_particular(capsys, monkeypatch,
                                                          tmp_path):
    """this tool used to have one developer's paths written into it."""
    monkeypatch.setattr(cli.paths, '_home', lambda: str(tmp_path))
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
    _code, out = run(capsys, 'paths')
    assert str(tmp_path) in out
