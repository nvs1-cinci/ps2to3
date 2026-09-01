"""installing into a data directory, and surviving a preset update.

installing writes into prusaslicer's own vendor directory, so the tests that
matter are the ones about not damaging what was already there.
"""

from __future__ import annotations

import os

import pytest

from ps2to3 import install
from ps2to3.files import read as read_text
from ps2to3.files import read_json
from ps2to3.files import write as write_text


@pytest.fixture
def datadir(tmp_path):
    """A data directory with a PrusaResearch vendor, as prusaslicer ships it."""
    target = tmp_path / 'dd' / 'presets' / 'local' / install.MERGE_REPO / 'PrusaResearch'
    target.mkdir(parents=True)
    (target / 'vendor.yaml').write_text(
        'kind: vendor\nid: PrusaResearch\nname: Prusa Research\n', encoding='utf-8')
    (target / 'preset-printer-mk4.yaml').write_text('kind: printer\n', encoding='utf-8')
    (target / 'assets').mkdir()
    (target / 'assets' / 'mk4_bed.stl').write_bytes(b'prusa\n')
    return str(tmp_path / 'dd')


@pytest.fixture
def build(tmp_path):
    """A converted build tree, as `convert` leaves it."""
    def make(vendor_id='Acme', assets=('acme_bed.stl',)):
        root = tmp_path / ('build-' + vendor_id)
        vdir = root / vendor_id / '1.0.0'
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / 'vendor.yaml').write_text('kind: vendor\n', encoding='utf-8')
        (vdir / f'preset-printer-{vendor_id.lower()}.yaml').write_text(
            'kind: printer\n', encoding='utf-8')
        (vdir / f'preset-print-{vendor_id.lower()}.yaml').write_text(
            'kind: print\n', encoding='utf-8')
        (vdir / 'manifest.json').write_text('[]', encoding='utf-8')
        if assets:
            (vdir / 'assets').mkdir(exist_ok=True)
            for a in assets:
                (vdir / 'assets' / a).write_bytes(b'solid\n')
        (root / 'vendor-fragment.yaml').write_text(
            f'---\nkind: printer\nid: {vendor_id.lower()}-one\n', encoding='utf-8')
        (root / 'manifest.json').write_text('{}', encoding='utf-8')
        return str(root)
    return make


def target_of(datadir):
    return os.path.join(datadir, 'presets', 'local', install.MERGE_REPO,
                        'PrusaResearch')


def listing(datadir):
    return sorted(os.listdir(target_of(datadir)))


# --------------------------------------------------------------------------- #
# installing
# --------------------------------------------------------------------------- #

def test_presets_and_assets_land_in_the_prusa_vendor(datadir, build):
    got = install.install_merge(build(), datadir, 'Acme')
    t = target_of(datadir)
    assert os.path.exists(os.path.join(t, 'preset-printer-acme.yaml'))
    assert os.path.exists(os.path.join(t, 'assets', 'acme_bed.stl'))
    assert got['files'] == 3


def test_the_converted_vendor_yaml_is_not_copied_over_prusas(datadir, build):
    """it would replace prusa's own vendor document with the conversion's."""
    install.install_merge(build(), datadir, 'Acme')
    text = read_text(os.path.join(target_of(datadir), 'vendor.yaml'))
    assert 'name: Prusa Research' in text


def test_the_fragment_is_appended_between_markers(datadir, build):
    install.install_merge(build(), datadir, 'Acme')
    text = read_text(os.path.join(target_of(datadir), 'vendor.yaml'))
    assert install.MARKER.format('Acme') in text
    assert install.END_MARKER.format('Acme') in text
    assert 'id: acme-one' in text


def test_prusas_own_files_are_untouched(datadir, build):
    mk4 = os.path.join(target_of(datadir), 'preset-printer-mk4.yaml')
    before = read_text(mk4)
    install.install_merge(build(), datadir, 'Acme')
    assert read_text(mk4) == before
    assert os.path.exists(os.path.join(target_of(datadir), 'assets', 'mk4_bed.stl'))


def test_installing_twice_does_not_duplicate_the_fragment(datadir, build):
    """the fragment declares printers; a second copy is a duplicate id."""
    install.install_merge(build(), datadir, 'Acme')
    install.install_merge(build(), datadir, 'Acme')
    text = read_text(os.path.join(target_of(datadir), 'vendor.yaml'))
    assert text.count('id: acme-one') == 1
    assert text.count(install.MARKER.format('Acme')) == 1


def test_two_vendors_coexist(datadir, build):
    install.install_merge(build('Acme'), datadir, 'Acme')
    install.install_merge(build('Bolt'), datadir, 'Bolt')
    text = read_text(os.path.join(target_of(datadir), 'vendor.yaml'))
    assert 'id: acme-one' in text and 'id: bolt-one' in text
    assert 'preset-printer-acme.yaml' in listing(datadir)
    assert 'preset-printer-bolt.yaml' in listing(datadir)


def test_a_data_directory_without_the_prusa_vendor_is_refused(tmp_path, build):
    with pytest.raises(SystemExit, match='no PrusaResearch vendor'):
        install.install_merge(build(), str(tmp_path / 'empty'), 'Acme')


def test_a_build_for_a_different_vendor_is_refused_by_name(datadir, build):
    with pytest.raises(SystemExit, match="no vendor dir 'Bolt'"):
        install.install_merge(build('Acme'), datadir, 'Bolt')


# --------------------------------------------------------------------------- #
# the features the host vendor has to declare
# --------------------------------------------------------------------------- #

VENDOR_WITH_FEATURES = """kind: vendor
id: PrusaResearch
name: Prusa Research
features:
  printer:
    supports_high_flow_nozzle:
      default: true
    supports_04_nozzle:
      default: true
  tool:
    nozzle_diameter:
      default: 0.4
---
kind: printer
id: mk4s
"""


def with_features(datadir, text=VENDOR_WITH_FEATURES):
    write_text(os.path.join(target_of(datadir), 'vendor.yaml'), text)


def fragment(build_dir, *features):
    body = ['---', 'kind: printer', 'id: acme-one', 'features:']
    for f in features:
        body += [f'  {f}:', '    default: false']
    write_text(os.path.join(build_dir, 'vendor-fragment.yaml'), '\n'.join(body) + '\n')


def test_a_feature_the_host_vendor_declares_installs(datadir, build):
    b = build()
    with_features(datadir)
    fragment(b, 'supports_high_flow_nozzle', 'supports_04_nozzle')
    assert install.install_merge(b, datadir, 'Acme')['files'] == 3


def test_a_feature_the_host_vendor_does_not_declare_is_refused(datadir, build):
    """an undeclared name is an unknown variable to the expression evaluator.

    3.0.0-alpha10 does not catch that: it came out as
    `EvalError: Unknown variable 'printer.supports_non_high_flow_nozzle'` and
    took the whole app with it, so it is checked before anything is copied.
    """
    b = build()
    with_features(datadir)
    fragment(b, 'supports_high_flow_nozzle', 'supports_non_high_flow_nozzle')
    with pytest.raises(SystemExit, match='supports_non_high_flow_nozzle'):
        install.install_merge(b, datadir, 'Acme')


def test_a_refused_install_copies_nothing(datadir, build):
    b = build()
    before = listing(datadir)
    with_features(datadir)
    fragment(b, 'made_up_feature')
    with pytest.raises(SystemExit):
        install.install_merge(b, datadir, 'Acme')
    assert listing(datadir) == before
    assert 'made_up' not in read_text(os.path.join(target_of(datadir), 'vendor.yaml'))


def test_a_tool_scoped_feature_counts_as_declared(datadir, build):
    """our tool docs set nozzle_diameter, which the vendor declares under tool."""
    b = build()
    with_features(datadir)
    fragment(b, 'nozzle_diameter')
    assert install.install_merge(b, datadir, 'Acme')['files'] == 3


def test_a_vendor_with_no_features_block_is_not_second_guessed(datadir, build):
    """a check that cannot read the file must not be what stops an install."""
    b = build()
    with_features(datadir, 'kind: vendor\nid: PrusaResearch\nname: Prusa Research\n')
    fragment(b, 'anything_at_all')
    assert install.install_merge(b, datadir, 'Acme')['files'] == 3


def test_the_five_real_fragments_only_use_declared_features(datadir, build):
    """the shape our own conversions emit, against a vendor block like prusa's."""
    b = build()
    with_features(datadir)
    fragment(b, 'supports_04_nozzle')
    assert not install.undeclared_features(
        read_text(os.path.join(b, 'vendor-fragment.yaml')), VENDOR_WITH_FEATURES)


# --------------------------------------------------------------------------- #
# uninstalling
# --------------------------------------------------------------------------- #

def test_uninstalling_removes_only_what_was_installed(datadir, build):
    before = listing(datadir)
    install.install_merge(build(), datadir, 'Acme')
    install.uninstall_merge(datadir, 'Acme')
    assert [f for f in listing(datadir) if not f.startswith('.')] == before
    text = read_text(os.path.join(target_of(datadir), 'vendor.yaml'))
    assert 'acme' not in text
    assert 'name: Prusa Research' in text


def test_uninstalling_one_vendor_leaves_the_other(datadir, build):
    install.install_merge(build('Acme'), datadir, 'Acme')
    install.install_merge(build('Bolt'), datadir, 'Bolt')
    install.uninstall_merge(datadir, 'Acme')
    text = read_text(os.path.join(target_of(datadir), 'vendor.yaml'))
    assert 'id: acme-one' not in text
    assert 'id: bolt-one' in text
    assert 'preset-printer-bolt.yaml' in listing(datadir)


def test_uninstalling_what_was_never_installed_is_not_an_error(datadir):
    assert install.uninstall_merge(datadir, 'Acme')['files'] == 0


def test_a_block_written_before_end_markers_existed_is_still_removable(datadir, build):
    """early versions appended without a closing marker; those installs exist."""
    install.install_merge(build(), datadir, 'Acme')
    vy = os.path.join(target_of(datadir), 'vendor.yaml')
    text = read_text(vy).replace(
        install.END_MARKER.format('Acme'), '')
    write_text(vy, text)
    install.uninstall_merge(datadir, 'Acme')
    assert 'acme' not in read_text(vy)


# --------------------------------------------------------------------------- #
# the registry, and surviving a preset update
# --------------------------------------------------------------------------- #

def test_the_registry_lives_outside_the_vendor_directory(datadir, build):
    """a preset update replaces the vendor directory wholesale.

    a record kept inside it goes with the printers it was meant to restore.
    """
    install.install_merge(build(), datadir, 'Acme')
    assert os.path.exists(os.path.join(datadir, install.REGISTRY))
    assert not any(f.startswith('ps2to3-installed')
                   for f in os.listdir(target_of(datadir)))


def test_the_registry_records_where_the_build_came_from(datadir, build):
    b = build()
    install.install_merge(b, datadir, 'Acme')
    reg = read_json(os.path.join(datadir, install.REGISTRY))
    assert reg['Acme']['build'] == os.path.abspath(b)


def test_listing_reports_an_install_as_present(datadir, build):
    install.install_merge(build(), datadir, 'Acme')
    rec, = install.list_injected(datadir)
    assert rec['vendor_id'] == 'Acme'
    assert rec['present'] and rec['buildable']


def test_listing_reports_an_install_a_preset_update_removed(datadir, build):
    install.install_merge(build(), datadir, 'Acme')
    wipe_vendor(datadir)
    rec, = install.list_injected(datadir)
    assert not rec['present']
    assert rec['buildable']


def wipe_vendor(datadir):
    """What a preset update does: the vendor directory is replaced."""
    t = target_of(datadir)
    for f in os.listdir(t):
        p = os.path.join(t, f)
        if os.path.isfile(p):
            os.remove(p)
    write_text(os.path.join(t, 'vendor.yaml'),
               'kind: vendor\nid: PrusaResearch\nname: Prusa Research\n')


def test_restore_puts_back_what_a_preset_update_removed(datadir, build):
    install.install_merge(build(), datadir, 'Acme')
    wipe_vendor(datadir)
    done, skipped = install.restore_all(datadir)
    assert done == ['Acme'] and skipped == []
    text = read_text(os.path.join(target_of(datadir), 'vendor.yaml'))
    assert 'id: acme-one' in text
    assert 'preset-printer-acme.yaml' in listing(datadir)


def test_restore_leaves_a_still_present_install_alone(datadir, build):
    install.install_merge(build(), datadir, 'Acme')
    done, skipped = install.restore_all(datadir)
    assert done == [] and skipped == []


def test_restore_names_what_it_cannot_rebuild(datadir, build):
    """the build tree can be gone; then only the user can fix it."""
    b = build()
    install.install_merge(b, datadir, 'Acme')
    wipe_vendor(datadir)
    for root, _d, fns in os.walk(b, topdown=False):
        for f in fns:
            os.remove(os.path.join(root, f))
        os.rmdir(root)
    done, skipped = install.restore_all(datadir)
    assert done == []
    assert [s['vendor_id'] for s in skipped] == ['Acme']


def test_an_install_made_before_the_registry_existed_is_still_listed(datadir, build):
    install.install_merge(build(), datadir, 'Acme')
    os.remove(os.path.join(datadir, install.REGISTRY))
    rec, = install.list_injected(datadir)
    assert rec['present'] and not rec['buildable']


def test_a_corrupt_registry_is_ignored_rather_than_fatal(datadir):
    write_text(os.path.join(datadir, install.REGISTRY), '{ truncated')
    assert install.read_registry(datadir) == {}


# --------------------------------------------------------------------------- #
# the repository path
# --------------------------------------------------------------------------- #

def test_the_repository_zip_holds_the_whole_build_but_not_the_fragment(build,
                                                                      monkeypatch):
    """the fragment is for merging; a repository would reject the extra document."""
    import zipfile

    calls = []
    monkeypatch.setattr(install.subprocess, 'run',
                        lambda cmd, **kw: calls.append(cmd))
    b = build()
    install.install_repo(b, '/nowhere', command=['prusa-slicer'])
    with zipfile.ZipFile(os.path.join(b, 'repository.zip')) as z:
        names = set(z.namelist())
    assert 'manifest.json' in names
    assert 'Acme/1.0.0/preset-printer-acme.yaml' in names
    assert 'vendor-fragment.yaml' not in names
    assert 'repository.zip' not in names
    assert any('--preset-update-add-local' in c for c in calls)


def test_no_slicer_means_a_clear_error_not_a_traceback(build, monkeypatch):
    monkeypatch.setattr(install.paths, 'slicer_command', lambda: None)
    with pytest.raises(SystemExit, match='was not found'):
        install.install_repo(build(), '/nowhere')
