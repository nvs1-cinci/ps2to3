"""discovering prusaslicer's locations.

these tests exist because the tool used to have one developer's paths written
into it.  every candidate now comes from the platform's own conventions, so the
tests pin each platform's layout with the environment mocked out.
"""

from __future__ import annotations

import os
import sys

import pytest

from ps2to3 import paths


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """A home directory with nothing in it, and a clean environment."""
    home = tmp_path / 'home' / 'someone'
    home.mkdir(parents=True)
    monkeypatch.setattr(paths, '_home', lambda: str(home))
    for var in ('APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME',
                'PROGRAMFILES', 'PROGRAMFILES(X86)', paths.ENV_DATA_DIR,
                paths.ENV_SLICER):
        monkeypatch.delenv(var, raising=False)
    return home


def platform(monkeypatch, name):
    monkeypatch.setattr(sys, 'platform', name)


def make_datadir(root, name='PrusaSlicer3-dev', vendor=True):
    d = root / name
    presets = d / 'presets' / 'local'
    presets.mkdir(parents=True)
    if vendor:
        v = presets / 'prusa-research-fff' / 'PrusaResearch'
        v.mkdir(parents=True)
        (v / 'vendor.yaml').write_text('kind: vendor\n', encoding='utf-8')
    return d


# --------------------------------------------------------------------------- #
# per-platform roots
# --------------------------------------------------------------------------- #

def test_linux_looks_under_xdg_config_home(fake_home, monkeypatch):
    platform(monkeypatch, 'linux')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(fake_home / 'conf'))
    d = make_datadir(fake_home / 'conf')
    found = paths.data_dirs()
    assert found[0].path == str(d)
    assert found[0].origin == 'XDG_CONFIG_HOME'
    assert found[0].installable


def test_linux_falls_back_to_dot_config(fake_home, monkeypatch):
    platform(monkeypatch, 'linux')
    d = make_datadir(fake_home / '.config')
    found = paths.data_dirs()
    assert found[0].path == str(d)
    assert found[0].origin == '~/.config'


def test_linux_finds_a_flatpak_install(fake_home, monkeypatch):
    """flatpak redirects ~/.config into a per-app sandbox, so ~/.config is empty."""
    platform(monkeypatch, 'linux')
    root = fake_home / '.var' / 'app' / paths.FLATPAK_ID / 'config'
    root.mkdir(parents=True)
    d = make_datadir(root)
    found = paths.data_dirs()
    assert found[0].path == str(d)
    assert found[0].origin == 'flatpak'


def test_linux_finds_a_snap_install(fake_home, monkeypatch):
    platform(monkeypatch, 'linux')
    root = fake_home / 'snap' / 'prusaslicer' / 'current' / '.config'
    root.mkdir(parents=True)
    d = make_datadir(root)
    assert paths.data_dirs()[0].path == str(d)


def test_windows_prefers_appdata_over_the_assumed_path(fake_home, monkeypatch):
    platform(monkeypatch, 'win32')
    appdata = fake_home / 'Roaming elsewhere'
    appdata.mkdir()
    monkeypatch.setenv('APPDATA', str(appdata))
    d = make_datadir(appdata)
    found = paths.data_dirs()
    assert found[0].path == str(d)
    assert found[0].origin == 'APPDATA'


def test_windows_works_without_appdata_set(fake_home, monkeypatch):
    platform(monkeypatch, 'win32')
    roaming = fake_home / 'AppData' / 'Roaming'
    roaming.mkdir(parents=True)
    d = make_datadir(roaming)
    assert paths.data_dirs()[0].path == str(d)


def test_macos_looks_in_application_support(fake_home, monkeypatch):
    platform(monkeypatch, 'darwin')
    root = fake_home / 'Library' / 'Application Support'
    root.mkdir(parents=True)
    d = make_datadir(root)
    found = paths.data_dirs()
    assert found[0].path == str(d)
    assert found[0].origin == 'Application Support'


def test_a_platform_only_offers_its_own_layout(fake_home, monkeypatch):
    """a windows path on linux would be an invitation to install nowhere."""
    platform(monkeypatch, 'linux')
    assert not any('AppData' in d.path or 'Application Support' in d.path
                   for d in paths.data_dirs())


# --------------------------------------------------------------------------- #
# choosing between candidates
# --------------------------------------------------------------------------- #

def test_the_environment_override_wins_even_before_it_exists(fake_home, monkeypatch):
    """the caller said so; a candidate that merely exists does not outrank that."""
    platform(monkeypatch, 'linux')
    make_datadir(fake_home / '.config')
    monkeypatch.setenv(paths.ENV_DATA_DIR, str(fake_home / 'elsewhere'))
    found = paths.data_dirs()
    assert found[0].path == str(fake_home / 'elsewhere')
    assert found[0].origin == paths.ENV_DATA_DIR
    assert not found[0].exists


def test_the_override_expands_a_tilde(fake_home, monkeypatch):
    platform(monkeypatch, 'linux')
    monkeypatch.setenv(paths.ENV_DATA_DIR, '~/mydir')
    assert paths.data_dirs()[0].path == os.path.expanduser('~/mydir')


def test_a_ready_directory_outranks_one_without_the_prusa_vendor(fake_home,
                                                                monkeypatch):
    platform(monkeypatch, 'linux')
    make_datadir(fake_home / '.config', 'PrusaSlicer3-dev', vendor=False)
    ready = make_datadir(fake_home / '.config', 'PrusaSlicer3')
    found = paths.data_dirs()
    assert found[0].path == str(ready)
    assert found[0].installable
    assert not found[1].installable


def test_a_directory_that_only_exists_is_reported_but_not_installable(fake_home,
                                                                     monkeypatch):
    """an empty directory is not somewhere a merge can go."""
    platform(monkeypatch, 'linux')
    (fake_home / '.config' / 'PrusaSlicer3-dev').mkdir(parents=True)
    d = paths.data_dirs()[0]
    assert d.exists and not d.has_presets and not d.installable
    assert 'empty' in d.label


def test_nothing_installed_still_offers_where_it_would_go(fake_home, monkeypatch):
    platform(monkeypatch, 'linux')
    found = paths.data_dirs()
    assert found
    assert found[0].path == str(fake_home / '.config' / 'PrusaSlicer3-dev')
    assert not found[0].exists
    assert 'not present' in found[0].label
    assert paths.default_data_dir() == found[0].path


def test_every_candidate_is_offered_once(fake_home, monkeypatch):
    """the roots overlap when XDG_CONFIG_HOME is set to ~/.config by hand."""
    platform(monkeypatch, 'linux')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(fake_home / '.config'))
    make_datadir(fake_home / '.config')
    seen = [d.path for d in paths.data_dirs()]
    assert len(seen) == len(set(seen))


def test_a_datadir_the_alpha_has_not_created_yet_is_not_claimed_ready(fake_home,
                                                                     monkeypatch):
    platform(monkeypatch, 'linux')
    d = make_datadir(fake_home / '.config', vendor=False)
    got = paths.data_dirs()[0]
    assert got.path == str(d)
    assert got.has_presets and not got.installable
    assert 'no PrusaResearch vendor yet' in got.label


# --------------------------------------------------------------------------- #
# 2.x bundles, offered as conversion sources
# --------------------------------------------------------------------------- #

def test_installed_2x_bundles_are_found(fake_home, monkeypatch):
    platform(monkeypatch, 'linux')
    vend = fake_home / '.config' / 'PrusaSlicer' / 'vendor'
    vend.mkdir(parents=True)
    (vend / 'PrusaResearch.ini').write_text('[vendor]\n', encoding='utf-8')
    (vend / 'Positron3D.ini').write_text('[vendor]\n', encoding='utf-8')
    (vend / 'PrusaResearch.idx').write_text('1.0.0\n', encoding='utf-8')
    got = paths.legacy_bundles()
    assert [os.path.basename(p) for p in got] == ['Positron3D.ini',
                                                  'PrusaResearch.ini']


def test_bundles_are_also_taken_from_a_3x_data_directory(fake_home, monkeypatch):
    """3.x keeps the 2.x bundles it imported, and they convert just as well."""
    platform(monkeypatch, 'linux')
    vend = fake_home / '.config' / 'PrusaSlicer3-dev' / 'vendor'
    vend.mkdir(parents=True)
    (vend / 'Acme.ini').write_text('[vendor]\n', encoding='utf-8')
    assert [os.path.basename(p) for p in paths.legacy_bundles()] == ['Acme.ini']


def test_no_bundles_is_an_empty_list_not_an_error(fake_home, monkeypatch):
    platform(monkeypatch, 'linux')
    assert paths.legacy_bundles() == []


# --------------------------------------------------------------------------- #
# the cache
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('plat,env,expected', [
    ('linux', {}, '.cache/ps2to3'),
    ('darwin', {}, 'Library/Caches/ps2to3'),
    ('win32', {}, 'AppData/Local/ps2to3'),
])
def test_cache_follows_the_platform_convention(fake_home, monkeypatch, plat, env,
                                               expected):
    platform(monkeypatch, plat)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    got = paths.cache_dir().replace(os.sep, '/')
    assert got == str(fake_home).replace(os.sep, '/') + '/' + expected


def test_cache_honours_xdg_cache_home(fake_home, monkeypatch):
    platform(monkeypatch, 'linux')
    monkeypatch.setenv('XDG_CACHE_HOME', str(fake_home / 'c'))
    assert paths.cache_dir() == str(fake_home / 'c' / 'ps2to3')


# --------------------------------------------------------------------------- #
# finding the slicer itself
# --------------------------------------------------------------------------- #

def test_the_slicer_override_is_split_like_a_command_line(fake_home, monkeypatch):
    monkeypatch.setenv(paths.ENV_SLICER, 'flatpak run com.prusa3d.PrusaSlicer')
    assert paths.slicer_command() == ['flatpak', 'run', 'com.prusa3d.PrusaSlicer']


def test_an_override_with_a_spaced_path_survives_quoting(fake_home, monkeypatch):
    monkeypatch.setenv(paths.ENV_SLICER, '"C:/Program Files/Prusa3D/ps.exe"')
    assert paths.slicer_command() == ['C:/Program Files/Prusa3D/ps.exe']


def test_a_flatpak_install_is_preferred_on_linux(fake_home, monkeypatch):
    platform(monkeypatch, 'linux')
    monkeypatch.setattr(paths.shutil, 'which',
                        lambda n: '/usr/bin/flatpak' if n == 'flatpak' else None)
    monkeypatch.setattr(paths, '_flatpak_has_app', lambda _f: True)
    assert paths.slicer_command() == ['/usr/bin/flatpak', 'run', paths.FLATPAK_ID]


def test_flatpak_without_the_app_installed_is_not_used(fake_home, monkeypatch):
    platform(monkeypatch, 'linux')
    monkeypatch.setattr(paths.shutil, 'which',
                        lambda n: '/usr/bin/' + n if n in ('flatpak', 'prusa-slicer')
                        else None)
    monkeypatch.setattr(paths, '_flatpak_has_app', lambda _f: False)
    assert paths.slicer_command() == ['/usr/bin/prusa-slicer']


def test_windows_looks_in_program_files(fake_home, monkeypatch):
    platform(monkeypatch, 'win32')
    pf = fake_home / 'Program Files'
    exe = pf / 'Prusa3D' / 'PrusaSlicer' / 'prusa-slicer-console.exe'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'MZ')
    monkeypatch.setenv('PROGRAMFILES', str(pf))
    monkeypatch.setattr(paths.shutil, 'which', lambda _n: None)
    assert paths.slicer_command() == [str(exe)]


def test_macos_looks_inside_the_app_bundle(fake_home, monkeypatch):
    platform(monkeypatch, 'darwin')
    exe = (fake_home / 'Applications' / 'PrusaSlicer.app' / 'Contents' / 'MacOS'
           / 'PrusaSlicer')
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'\xcf\xfa')
    monkeypatch.setattr(paths.shutil, 'which', lambda _n: None)
    assert paths.slicer_command() == [str(exe)]


def test_no_slicer_anywhere_is_none_rather_than_a_guess(fake_home, monkeypatch):
    platform(monkeypatch, 'linux')
    monkeypatch.setattr(paths.shutil, 'which', lambda _n: None)
    assert paths.slicer_command() is None


def test_a_broken_flatpak_binary_does_not_propagate(fake_home, monkeypatch):
    def boom(*_a, **_kw):
        raise OSError('no such file')
    monkeypatch.setattr(paths.subprocess, 'run', boom)
    assert paths._flatpak_has_app('/usr/bin/flatpak') is False
