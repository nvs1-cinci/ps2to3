"""where prusaslicer keeps its files, per platform.

nothing here is hardcoded to one machine. candidate locations come from the
platform's own conventions plus the environment, and a candidate is only
reported when the directory on disk actually looks like what it claims to be.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

# the alpha names its data directory PrusaSlicer3-dev. the release name is not
# settled, so every plausible name is tried and whichever exists wins
DATA_DIR_NAMES = ('PrusaSlicer3-dev', 'PrusaSlicer3', 'PrusaSlicer-alpha')

# 2.x, the source of profiles rather than the target
LEGACY_DIR_NAMES = ('PrusaSlicer',)

ENV_DATA_DIR = 'PS2TO3_DATADIR'
ENV_SLICER = 'PS2TO3_SLICER'

FLATPAK_ID = 'com.prusa3d.PrusaSlicer'


@dataclass(frozen=True)
class DataDir:
    """a candidate prusaslicer data directory."""

    path: str
    origin: str
    exists: bool
    has_presets: bool
    has_prusa_vendor: bool

    @property
    def installable(self) -> bool:
        """merging needs prusa's own vendor directory to merge into."""
        return self.has_prusa_vendor

    @property
    def label(self) -> str:
        if self.has_prusa_vendor:
            state = 'ready'
        elif self.has_presets:
            state = 'no PrusaResearch vendor yet'
        elif self.exists:
            state = 'empty'
        else:
            state = 'not present'
        return f'{self.path}  ({self.origin}, {state})'


def _home() -> str:
    return os.path.expanduser('~')


def _config_roots() -> list[tuple[str, str]]:
    """(root, origin) pairs that prusaslicer puts its data directory under."""
    roots: list[tuple[str, str]] = []
    if sys.platform == 'win32':
        appdata = os.environ.get('APPDATA')
        if appdata:
            roots.append((appdata, 'APPDATA'))
        roots.append((os.path.join(_home(), 'AppData', 'Roaming'), 'AppData/Roaming'))
    elif sys.platform == 'darwin':
        roots.append((os.path.join(_home(), 'Library', 'Application Support'),
                      'Application Support'))
    else:
        xdg = os.environ.get('XDG_CONFIG_HOME')
        roots.append((xdg or os.path.join(_home(), '.config'),
                      'XDG_CONFIG_HOME' if xdg else '~/.config'))
        # flatpak redirects ~/.config into its own per-app sandbox
        roots.append((os.path.join(_home(), '.var', 'app', FLATPAK_ID, 'config'),
                      'flatpak'))
        # snap keeps a versioned home with the same layout inside
        snap = os.path.join(_home(), 'snap', 'prusaslicer', 'current', '.config')
        roots.append((snap, 'snap'))
    seen: set[str] = set()
    out = []
    for root, origin in roots:
        key = os.path.normpath(root)
        if key not in seen:
            seen.add(key)
            out.append((root, origin))
    return out


def _inspect(path: str, origin: str) -> DataDir:
    presets = os.path.join(path, 'presets', 'local')
    vendor = os.path.join(presets, 'prusa-research-fff', 'PrusaResearch', 'vendor.yaml')
    return DataDir(path=path, origin=origin,
                   exists=os.path.isdir(path),
                   has_presets=os.path.isdir(presets),
                   has_prusa_vendor=os.path.isfile(vendor))


def data_dirs() -> list[DataDir]:
    """every prusaslicer 3 data directory this machine appears to have.

    ordered most usable first, so the head of the list is the sensible default.
    an explicit `PS2TO3_DATADIR` always comes first, even if it does not exist
    yet, because the caller said so.
    """
    found: list[DataDir] = []
    override = os.environ.get(ENV_DATA_DIR)
    forced = [_inspect(os.path.expanduser(override), ENV_DATA_DIR)] if override else []
    for root, origin in _config_roots():
        for name in DATA_DIR_NAMES:
            cand = _inspect(os.path.join(root, name), origin)
            if cand.exists or not (found or forced):
                found.append(cand)
    # the override is not ranked with the rest: it is what the caller asked for,
    # and quietly using a better-looking directory instead is how a conversion
    # ends up installed somewhere nobody was looking
    ordered = forced + sorted(found, key=lambda d: (not d.has_prusa_vendor,
                                                    not d.has_presets, not d.exists))
    seen: set[str] = set()
    out = []
    for d in ordered:
        key = os.path.normpath(d.path)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def default_data_dir() -> str:
    """the data directory to offer first. a path either way, never empty."""
    dirs = data_dirs()
    if dirs:
        return dirs[0].path
    root, _origin = _config_roots()[0]
    return os.path.join(root, DATA_DIR_NAMES[0])


def legacy_vendor_dirs() -> list[str]:
    """prusaslicer 2.x vendor directories, where its profile bundles live.

    the app offers these as conversion sources so nobody has to hunt for a
    bundle they already have installed.
    """
    out = []
    for root, _origin in _config_roots():
        for name in LEGACY_DIR_NAMES + DATA_DIR_NAMES:
            cand = os.path.join(root, name, 'vendor')
            if os.path.isdir(cand):
                out.append(cand)
    return out


def legacy_bundles() -> list[str]:
    """every 2.x vendor bundle installed on this machine."""
    out = []
    for d in legacy_vendor_dirs():
        for entry in sorted(os.listdir(d)):
            if entry.lower().endswith('.ini'):
                out.append(os.path.join(d, entry))
    return out


def cache_dir() -> str:
    """where to keep the cached config schema."""
    if sys.platform == 'win32':
        root = os.environ.get('LOCALAPPDATA') or os.path.join(
            _home(), 'AppData', 'Local')
    elif sys.platform == 'darwin':
        root = os.path.join(_home(), 'Library', 'Caches')
    else:
        root = os.environ.get('XDG_CACHE_HOME') or os.path.join(_home(), '.cache')
    return os.path.join(root, 'ps2to3')


def _windows_slicer_candidates() -> list[str]:
    out = []
    for var in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        root = os.environ.get(var)
        if not root:
            continue
        for exe in ('prusa-slicer-console.exe', 'PrusaSlicer.exe'):
            out.append(os.path.join(root, 'Prusa3D', 'PrusaSlicer', exe))
    return out


def slicer_command() -> list[str] | None:
    """how to run prusaslicer 3 on this machine, or none if it is not found.

    only needed to export the config schema; a schema shipped with the package
    means the tool works without prusaslicer installed at all.
    """
    override = os.environ.get(ENV_SLICER)
    if override:
        import shlex
        return shlex.split(override)

    if sys.platform == 'win32':
        for cand in _windows_slicer_candidates():
            if os.path.isfile(cand):
                return [cand]
    elif sys.platform == 'darwin':
        for cand in ('/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer',
                     os.path.join(_home(), 'Applications', 'PrusaSlicer.app',
                                  'Contents', 'MacOS', 'PrusaSlicer')):
            if os.path.isfile(cand):
                return [cand]
    else:
        flatpak = shutil.which('flatpak')
        if flatpak and _flatpak_has_app(flatpak):
            return [flatpak, 'run', FLATPAK_ID]

    for name in ('prusa-slicer', 'PrusaSlicer', 'prusa-slicer-console'):
        found = shutil.which(name)
        if found:
            return [found]
    return None


def _flatpak_has_app(flatpak: str) -> bool:
    try:
        done = subprocess.run([flatpak, 'info', FLATPAK_ID],
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0
