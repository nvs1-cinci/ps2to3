"""putting a converted repository into a prusaslicer 3.x data directory.

3.0.0-alpha10 only exposes the vendor whose id is `PrusaResearch`, so a
conversion is merged into that vendor rather than added beside it. see
docs/decisions/0001-merge-into-the-prusaresearch-vendor.md
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import zipfile

from . import files, paths

MERGE_VENDOR = 'PrusaResearch'
MERGE_REPO = 'prusa-research-fff'

MARKER = '# >>> ps2to3: {} >>>'
END_MARKER = '# <<< ps2to3: {} <<<'


# A preset update replaces the whole vendor directory, taking the injected files
# and their manifests with it, so the record of what was installed is kept beside
# the data directory instead of inside the vendor.
REGISTRY = 'ps2to3-installed.json'


def _registry_path(datadir):
    return os.path.join(datadir, REGISTRY)


def read_registry(datadir):
    path = _registry_path(datadir)
    if not os.path.exists(path):
        return {}
    try:
        return files.read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}


def write_registry(datadir, reg):
    files.write_json(_registry_path(datadir), reg, indent=1, sort_keys=True)


def _merge_target(datadir):
    target = os.path.join(datadir, 'presets', 'local', MERGE_REPO, MERGE_VENDOR)
    if not os.path.isdir(target):
        raise SystemExit(f'no {MERGE_VENDOR} vendor at {target}')
    return target


def _remove_injection(target, vendor_id):
    """Undo a previous injection of `vendor_id`.  Returns files removed."""
    removed = 0
    manifest = os.path.join(target, '.ps2to3-' + vendor_id + '.files')
    if os.path.exists(manifest):
        for rel in files.read(manifest).split('\n'):
            if not rel:
                continue
            p = os.path.join(target, rel)
            if os.path.exists(p):
                os.remove(p)
                removed += 1
        os.remove(manifest)
    vy = os.path.join(target, 'vendor.yaml')
    text = files.read(vy)
    start, end = MARKER.format(vendor_id), END_MARKER.format(vendor_id)
    i = text.find(start)
    if i != -1:
        j = text.find(end, i)
        # a block written before end markers existed runs to the end of the file
        tail = '' if j == -1 else text[j + len(end):]
        text = text[:i] + tail
        files.write(vy, text.rstrip('\n') + '\n')
    return removed


# A printer's features are declared once, vendor-level, and a printer doc only
# overrides them.  Merging appends our printer docs to somebody else's vendor, so
# every feature name they use has to be one that vendor declares: an undeclared
# name is an unknown variable to the expression evaluator, and 3.0.0-alpha10 does
# not catch that.  It came out as
#   terminate called after throwing an instance of 'Slic3r::Biz::Expr::EvalError'
#     what():  Unknown variable 'printer.supports_non_high_flow_nozzle'
# which takes the whole app with it, so this is checked before anything is copied.

def _declared_features(vendor_yaml_text):
    """{scope: {feature name}} from a vendor document's own features block."""
    out = {}
    scope = None
    in_features = False
    for line in vendor_yaml_text.split('\n'):
        if line.startswith('---'):                  # only the first document
            break
        if line.rstrip() == 'features:':
            in_features = True
            continue
        if not in_features:
            continue
        if line and not line.startswith(' '):       # back to a top-level key
            break
        m = re.match(r'^  ([a-z_]+):\s*$', line)
        if m:
            scope = m.group(1)
            out.setdefault(scope, set())
            continue
        m = re.match(r'^    ([a-z_0-9]+):\s*$', line)
        if m and scope:
            out[scope].add(m.group(1))
    return out


def _fragment_features(fragment_text):
    """{feature name} that a vendor fragment's printer docs set."""
    out = set()
    in_features = False
    for line in fragment_text.split('\n'):
        if line.rstrip() == 'features:':
            in_features = True
            continue
        if not in_features:
            continue
        m = re.match(r'^  ([a-z_0-9]+):\s*$', line)
        if m:
            out.add(m.group(1))
            continue
        if line and not line.startswith('    '):
            in_features = False
    return out


def undeclared_features(fragment_text, vendor_yaml_text):
    """Feature names the fragment sets that the host vendor never declares.

    Empty when the host's features block cannot be found: a check that cannot
    read the file must not be the thing that stops an install.
    """
    declared = _declared_features(vendor_yaml_text)
    if not declared.get('printer'):
        return set()
    known = set().union(*declared.values())
    return _fragment_features(fragment_text) - known


def install_merge(build, datadir, vendor_id):
    """Inject a converted vendor into the PrusaResearch vendor (alpha10 only
    exposes that one).  Idempotent: re-running replaces a previous injection."""
    vdir = _sole_version_dir(build, vendor_id)
    target = _merge_target(datadir)
    vy = os.path.join(target, 'vendor.yaml')
    frag = files.read(os.path.join(build, 'vendor-fragment.yaml'))
    unknown = undeclared_features(frag, files.read(vy))
    if unknown:
        raise SystemExit(
            f'ps2to3: {os.path.basename(vy)} does not declare '
            + ', '.join(sorted(unknown))
            + ', which this conversion\'s printers set. installing it would make '
              'prusaslicer terminate on an unknown variable. convert again against '
              'this prusaslicer (ps2to3 schema), or report the renamed feature')
    _remove_injection(target, vendor_id)
    copied = []
    for fn in sorted(os.listdir(vdir)):
        src = os.path.join(vdir, fn)
        if not os.path.isfile(src) or not fn.startswith('preset-'):
            continue
        shutil.copy2(src, os.path.join(target, fn))
        copied.append(fn)
    adir = os.path.join(vdir, 'assets')
    if os.path.isdir(adir):
        os.makedirs(os.path.join(target, 'assets'), exist_ok=True)
        for fn in sorted(os.listdir(adir)):
            shutil.copy2(os.path.join(adir, fn),
                         os.path.join(target, 'assets', fn))
            copied.append(os.path.join('assets', fn))
    with open(vy, 'a', encoding='utf-8') as f:
        f.write('\n' + MARKER.format(vendor_id) + '\n' + frag.rstrip('\n') + '\n'
                + END_MARKER.format(vendor_id) + '\n')
    files.write(os.path.join(target, '.ps2to3-' + vendor_id + '.files'),
                '\n'.join(copied))
    reg = read_registry(datadir)
    reg[vendor_id] = {'build': os.path.abspath(build), 'files': len(copied)}
    write_registry(datadir, reg)
    return {'target': target, 'files': len(copied)}


def uninstall_merge(datadir, vendor_id):
    target = _merge_target(datadir)
    removed = _remove_injection(target, vendor_id)
    reg = read_registry(datadir)
    if reg.pop(vendor_id, None) is not None:
        write_registry(datadir, reg)
    return {'target': target, 'files': removed}


def list_injected(datadir):
    """Every conversion ever installed, and whether it is present right now."""
    target = _merge_target(datadir)
    present = {f[len('.ps2to3-'):-len('.files')]
               for f in os.listdir(target)
               if f.startswith('.ps2to3-') and f.endswith('.files')}
    out = []
    for vendor_id, rec in sorted(read_registry(datadir).items()):
        build = rec.get('build', '')
        out.append({'vendor_id': vendor_id, 'build': build,
                    'present': vendor_id in present,
                    'buildable': bool(build) and os.path.isdir(build)})
    for vendor_id in sorted(present - {o['vendor_id'] for o in out}):
        out.append({'vendor_id': vendor_id, 'build': '', 'present': True,
                    'buildable': False})
    return out


def restore_all(datadir):
    """Reinstall everything the registry knows about that is not present.

    A PrusaSlicer preset update replaces the PrusaResearch vendor directory and
    silently takes every injected printer with it
    this puts them back.
    """
    done, skipped = [], []
    for rec in list_injected(datadir):
        if rec['present']:
            continue
        if not rec['buildable']:
            skipped.append(rec)
            continue
        install_merge(rec['build'], datadir, rec['vendor_id'])
        done.append(rec['vendor_id'])
    return done, skipped


def install_repo(build, datadir, command=None, select=True):
    """Package the conversion as a local repository and register it."""
    zip_path = os.path.join(build, 'repository.zip')
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, fns in os.walk(build):
            for fn in fns:
                p = os.path.join(root, fn)
                if os.path.abspath(p) == os.path.abspath(zip_path):
                    continue
                if fn == 'vendor-fragment.yaml':
                    continue
                z.write(p, os.path.relpath(p, build))
    command = command or paths.slicer_command()
    if not command:
        raise SystemExit('prusaslicer 3 was not found, so a local repository '
                         f'cannot be registered. set {paths.ENV_SLICER}')
    subprocess.run(list(command) + ['--datadir', datadir,
                                    '--preset-update-add-local',
                                    os.path.abspath(zip_path)],
                   capture_output=True, text=True, timeout=900)
    if select:
        subprocess.run(list(command) + ['--datadir', datadir, '--preset-update'],
                       capture_output=True, text=True, timeout=1800)
    return {'zip': zip_path}


def _sole_version_dir(build, vendor_id):
    vd = os.path.join(build, vendor_id)
    if not os.path.isdir(vd):
        cands = [d for d in os.listdir(build) if os.path.isdir(os.path.join(build, d))]
        raise SystemExit(f'no vendor dir {vendor_id!r} in {build} (have: {cands})')
    versions = sorted(os.listdir(vd))
    return os.path.join(vd, versions[-1])
