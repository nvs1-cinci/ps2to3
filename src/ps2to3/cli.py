"""command line entry point."""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys

from . import orca, paths
from .bundle import SourceError, open_bundle
from .convert import Conversion
from .emit import slug
from .install import install_merge, install_repo, list_injected, restore_all, uninstall_merge
from .schema import Schema, SchemaUnavailable, export_schema
from .verify import verify

WARNING = """\
prusaslicer 3 is an early alpha and prusa only tests it with the printers it ships.
this is unofficial, unsupported, and can break things. a converted profile is a
translation - read the conversion notes, and check the g-code before you trust it.
if prusaslicer 3 crashes with a converted printer selected, do not report it to
prusa: remove these printers and reproduce it on stock profiles first."""


def _load_schema(args):
    try:
        return Schema.load(getattr(args, 'schema', None))
    except SchemaUnavailable as e:
        raise SystemExit(f'ps2to3: {e}') from None


def _resolve_datadir(given):
    if given:
        return os.path.expanduser(given)
    found = paths.data_dirs()
    ready = [d for d in found if d.installable]
    if not ready:
        lines = '\n'.join(f'  {d.label}' for d in found) or '  (none)'
        raise SystemExit(
            'ps2to3: no prusaslicer 3 data directory with a PrusaResearch vendor '
            f'was found. looked at:\n{lines}\n'
            f'pass --datadir, or set {paths.ENV_DATA_DIR}')
    return ready[0].path


def cmd_paths(args):
    print(f'platform        {sys.platform}')
    cmd = paths.slicer_command()
    print(f'prusaslicer 3   {" ".join(cmd) if cmd else "not found"}')
    print(f'schema cache    {Schema.cached_path()}')
    print(f'schema shipped  {Schema.shipped_path()}')
    print('data directories')
    for d in paths.data_dirs():
        print(f'  {d.label}')
    bundles = paths.legacy_bundles()
    print(f'2.x bundles     {len(bundles)} found')
    for b in bundles:
        print(f'  {b}')
    return 0


def cmd_schema(args):
    out = args.output or Schema.cached_path()
    try:
        print(f'wrote {export_schema(out, datadir=args.datadir)}')
    except SchemaUnavailable as e:
        raise SystemExit(f'ps2to3: {e}') from None
    return 0


def cmd_convert(args):
    schema = _load_schema(args)
    bad = orca.check_targets(schema.names())
    if bad:
        print('warning: rename targets missing from the 3.x schema')
        for x in bad:
            print(f'  {x}')

    notes: list[str] = []
    try:
        bundle = open_bundle(args.source, note=notes.append,
                             extra_trees=tuple(args.filament_library or ()),
                             valid_names=schema.names(), fix_gcode=args.fix_gcode,
                             schema=schema)
    except SourceError as e:
        raise SystemExit(f'ps2to3: {e}') from None
    conv = Conversion(bundle, schema, vendor_id=args.vendor_id,
                      vendor_name=args.vendor_name, repo_id=args.repo_id,
                      version=args.version, assets_dir=args.assets,
                      fix_gcode=args.fix_gcode,
                      visual={'bed_model': args.bed_model,
                              'bed_texture': args.bed_texture,
                              'thumbnail': args.thumbnail})
    for m in notes:
        conv.conv.note(m)
    out = args.output or os.path.join('build', slug(conv.vendor_id))
    info = conv.emit(out)

    print(f'{conv.vendor_name} ({conv.vendor_id}) -> {out}')
    print(f'  printer models    {info["models"]}')
    for m in conv.models.values():
        print(f'    {m.display} - {_shape(m)}, nozzles '
              + ', '.join(t.label for t in m.tools))
    print(f'  print presets     {info["print_presets"]}')
    print(f'  filament presets  {info["filament_presets"]}')
    print(f'  assets            {info["assets"]}')

    if conv.skipped:
        by_kind = collections.Counter(k for k, _n in conv.skipped)
        counts = ', '.join(f'{n} {k}' for k, n in by_kind.items())
        print(f'\n  {len(conv.skipped)} preset(s) skipped, their compatibility '
              f'condition matches no printer in this source ({counts})')
        for kind, name in conv.skipped[:8]:
            print(f'    {kind}: {name}')
        if len(conv.skipped) > 8:
            print(f'    and {len(conv.skipped) - 8} more')

    if conv.conv.notes:
        print(f'\n  {sum(conv.conv.notes.values())} conversion note(s)')
        for msg, n in conv.conv.notes.most_common():
            print(f'    x{n:<4} {msg}')

    if args.report:
        _write_report(args.report, conv, info)
        print(f'\n  report {args.report}')
    return 0


def _shape(model):
    if model.is_toolchanger:
        return f'{model.extruders}-tool changer'
    if model.is_mmu:
        return f'one tool, {model.extruders}-slot mmu feeder'
    return 'single tool'


def _write_report(path, conv, info):
    payload = {
        'vendor_id': conv.vendor_id,
        'vendor_name': conv.vendor_name,
        'repo_id': conv.repo_id,
        'version': conv.version,
        **{k: v for k, v in info.items() if k != 'vendor_dir'},
        'models': {m.id: {'name': m.display, 'shape': _shape(m),
                          'tools': [t.tid for t in m.tools]}
                   for m in conv.models.values()},
        'skipped': [{'kind': k, 'name': n} for k, n in conv.skipped],
        'notes': dict(conv.conv.notes),
    }
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, indent=2)


def cmd_install(args):
    datadir = _resolve_datadir(args.datadir)
    if args.mode == 'merge' and not args.yes:
        print(WARNING)
        print()
    vendor_id = args.vendor_id or _guess_vendor(args.build)
    if args.mode == 'merge':
        got = install_merge(args.build, datadir, vendor_id)
        print(f'merged {vendor_id} into {got["target"]} ({got["files"]} files)')
        print('a preset update replaces that vendor and removes this. '
              'run `ps2to3 restore` afterwards')
    else:
        got = install_repo(args.build, datadir)
        print(f'registered local repository {got["zip"]}')
    return 0


def cmd_uninstall(args):
    datadir = _resolve_datadir(args.datadir)
    if not args.vendor_id:
        listing = list_injected(datadir)
        if not listing:
            print('nothing installed by ps2to3')
            return 0
        for rec in listing:
            if rec['present']:
                state = 'installed'
            elif rec['buildable']:
                state = 'missing, a preset update removed it. run `ps2to3 restore`'
            else:
                state = 'missing, and its build directory is gone. convert it again'
            print(f'  {rec["vendor_id"]:16} {state}')
        return 0
    got = uninstall_merge(datadir, args.vendor_id)
    print(f'removed {args.vendor_id} from {got["target"]} ({got["files"]} files)')
    return 0


def cmd_restore(args):
    datadir = _resolve_datadir(args.datadir)
    done, skipped = restore_all(datadir)
    if done:
        print('restored ' + ', '.join(done))
    for rec in skipped:
        print(f'  {rec["vendor_id"]}: cannot restore, build directory '
              f'{rec["build"] or "unknown"} is gone. convert it again')
    if not done and not skipped:
        print('everything in the registry is already installed')
    return 0


def cmd_verify(args):
    schema = _load_schema(args)
    vendor_id = args.vendor_id or _guess_vendor(args.build)
    try:
        checked, bad, problems, collapsed = verify(args.source, args.build, schema,
                                                   vendor_id)
    except SourceError as e:
        raise SystemExit(f'ps2to3: {e}') from None
    print(f'compared {checked} text and g-code values, {bad} problem(s)')
    if collapsed:
        print(f'{len(collapsed)} printer preset(s) not compared, 2.x has several '
              f'presets for one nozzle and only the first is represented')
        for n in collapsed[:6]:
            print(f'    {n}')
        if len(collapsed) > 6:
            print(f'    and {len(collapsed) - 6} more')
    for p in problems[:args.limit]:
        print(p)
    if len(problems) > args.limit:
        print(f'and {len(problems) - args.limit} more')
    return 1 if bad else 0


def _guess_vendor(build):
    for d in sorted(os.listdir(build)):
        if os.path.isdir(os.path.join(build, d)):
            return d
    raise SystemExit(f'ps2to3: no vendor directory inside {build}')


def build_parser():
    ap = argparse.ArgumentParser(
        prog='ps2to3',
        description='convert printer profiles into the prusaslicer 3.x format')
    sub = ap.add_subparsers(dest='command', required=True)

    p = sub.add_parser('paths', help='show the locations this machine uses')
    p.set_defaults(func=cmd_paths)

    p = sub.add_parser('schema', help='export the 3.x option schema')
    p.add_argument('-o', '--output')
    p.add_argument('--datadir')
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser('convert', help='convert a source to 3.x yaml')
    p.add_argument('source', help='2.x .ini, orca/bambu .json, or a .3mf')
    p.add_argument('-o', '--output', help='output repository directory')
    p.add_argument('--vendor-id')
    p.add_argument('--vendor-name')
    p.add_argument('--repo-id')
    p.add_argument('--version', default='1.0.0')
    p.add_argument('--assets', help='directory holding the printer artwork')
    p.add_argument('--bed-model', metavar='FILE')
    p.add_argument('--bed-texture', metavar='FILE')
    p.add_argument('--thumbnail', metavar='FILE')
    p.add_argument('--filament-library', action='append', metavar='INDEX.json',
                   help='extra orca vendor index whose filaments to load')
    p.add_argument('--schema', help='config schema json')
    p.add_argument('--report', help='write a json conversion report here')
    p.add_argument('--fix-gcode', action='store_true',
                   help='neutralise custom-g-code placeholders 3.x removed')
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser('install', help='install a conversion into a data directory')
    p.add_argument('build')
    p.add_argument('--datadir')
    p.add_argument('--mode', choices=('merge', 'repo'), default='merge')
    p.add_argument('--vendor-id')
    p.add_argument('-y', '--yes', action='store_true', help='skip the warning')
    p.set_defaults(func=cmd_install)

    p = sub.add_parser('restore', help='reinstall what a preset update removed')
    p.add_argument('--datadir')
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser('uninstall', help='remove a conversion, or list them')
    p.add_argument('vendor_id', nargs='?')
    p.add_argument('--datadir')
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser('verify', help='compare a conversion against its source')
    p.add_argument('source')
    p.add_argument('build')
    p.add_argument('--vendor-id')
    p.add_argument('--schema')
    p.add_argument('--limit', type=int, default=20)
    p.set_defaults(func=cmd_verify)

    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == '__main__':
    sys.exit(main())
