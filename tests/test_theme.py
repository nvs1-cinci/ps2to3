"""the palette, which is prusaslicer 3's own rather than invented.

the window is not testable without a display, so what is pinned here is the
provenance: change a colour and a test says which of the app's own resources it
came from.
"""

from __future__ import annotations

import dataclasses

import pytest

from ps2to3.gui import theme


def test_the_accent_is_the_orange_prusaslicer_draws_its_icons_in():
    """#ED6B21 is the fill in 433 of the svgs the app ships."""
    assert theme.ACCENT == '#ED6B21'
    assert theme.LIGHT.accent == theme.ACCENT
    assert theme.DARK.accent == theme.ACCENT


def test_hover_uses_the_orange_from_its_newer_web_assets():
    assert theme.ACCENT_HOT == '#FA6831'


def test_the_dark_ground_is_the_one_its_dark_pages_use():
    assert theme.DARK.bg == '#121212'
    assert theme.DARK.text == '#E0E0E0'


def test_the_light_ground_is_the_grey_its_icons_are_drawn_on():
    assert theme.LIGHT.bg == '#F7F7F7'
    assert theme.LIGHT.text == '#333333'


def test_both_palettes_define_every_role():
    """a role a palette forgets is a widget with no colour in that theme."""
    fields = {f.name for f in dataclasses.fields(theme.Palette)}
    for palette in (theme.LIGHT, theme.DARK):
        for name in fields:
            assert getattr(palette, name), f'{palette.name} has no {name}'


@pytest.mark.parametrize('palette', [theme.LIGHT, theme.DARK])
def test_every_colour_is_a_hex_literal(palette):
    for f in dataclasses.fields(theme.Palette):
        if f.name == 'name':
            continue
        value = getattr(palette, f.name)
        assert value.startswith('#') and len(value) == 7, f'{f.name}={value}'


def test_inter_is_first_choice_because_the_slicer_ships_it():
    assert theme.FONT_CANDIDATES[0] == 'Inter'


def test_a_desktop_that_does_not_say_gets_the_light_theme(monkeypatch):
    """the slicer's own default, and the safer guess on a machine with no setting."""
    def boom(*_a, **_kw):
        raise OSError('no gsettings here')
    monkeypatch.setattr(theme.subprocess, 'run', boom)
    assert theme.prefers_dark() is False


def test_a_dark_desktop_is_followed(monkeypatch):
    class Done:
        stdout = "'prefer-dark'\n"
    monkeypatch.setattr(theme.sys, 'platform', 'linux')
    monkeypatch.setattr(theme.subprocess, 'run', lambda *_a, **_kw: Done())
    assert theme.prefers_dark() is True


# --------------------------------------------------------------------------- #
# what the licence asks the interface to keep
# --------------------------------------------------------------------------- #

def test_the_package_states_its_author_and_licence():
    """SWAtt v1 asks a derivative to keep this in the source, so it is here to
    keep - and a refactor that drops it should fail a test, not a licence."""
    import ps2to3
    assert ps2to3.__author__ == 'Nomadsgalaxy'
    assert ps2to3.__url__ == 'https://nomadsgalaxy.com'
    assert ps2to3.__license__ == 'OCL v1.1 + SWAtt v1'


def test_the_window_shows_the_author_and_licence():
    """SWAtt v1 asks for it in the user interface too."""
    import pathlib as _pathlib
    src = (_pathlib.Path(__file__).resolve().parents[1]
           / 'src' / 'ps2to3' / 'gui' / 'app.py').read_text()
    assert '__author__' in src and '__license__' in src
    assert '__url__' in src        # and the site is a link, not just text


def test_the_licence_file_names_the_version_and_the_addon():
    """a distribution has to reference both, or the add-on is not in effect."""
    import pathlib as _pathlib
    text = (_pathlib.Path(__file__).resolve().parents[1] / 'LICENSE').read_text()
    assert 'OCL v1.1 + SWAtt v1' in text
    assert 'Open Community License (OCL v1.1)' in text
    assert 'Software Attribution (SWAtt v1)' in text
    assert 'Nomadsgalaxy' in text
    assert 'nomadsgalaxy.com' in text
