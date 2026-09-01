"""building a 3.x preset repository from a parsed source."""

from __future__ import annotations

import collections
import hashlib
import os
import re
import shutil
import zipfile

from . import files
from .conditions import ConditionEvaluator
from .emit import mkid, slug, yscalar, yvalues
from .hardware import NOZZLE_FEATURE, PrinterVariant, VendorModel
from .values import META_KEYS, Converter


class Conversion:
    def __init__(self, bundle, schema, vendor_id=None, vendor_name=None,
                 repo_id=None, version='1.0.0', assets_dir=None, fix_gcode=False,
                 visual=None):
        self.b = bundle
        self.schema = schema
        self.conv = Converter(schema, fix_gcode=fix_gcode)
        self.vendor_id = vendor_id or self._default_vendor_id()
        self.vendor_name = vendor_name or bundle.vendor.get('name') or self.vendor_id
        self.repo_id = repo_id or bundle.vendor.get('repo_id') or slug(self.vendor_id).lower()
        self.version = version
        self.assets_dir = assets_dir or self._guess_assets()
        # A config bundle exported from the GUI carries no printer_model section
        # and so names no bed model; these fill that in.
        self.visual_override = {k: v for k, v in (visual or {}).items() if v}
        self.models = self._build_models()
        self._warn_multi_tool()
        self.print_meta = {}          # preset name -> list[(model, Tool)]
        self.skipped = []             # (kind, preset name) with no matching printer
        self.missing_keys = set()     # options a condition read but no preset sets
        self._cond_cache = {}
        self._known_cache = {}

    # -- setup ------------------------------------------------------------- #
    def _default_vendor_id(self):
        base = os.path.basename(self.b.path)
        return re.sub(r'\.ini$', '', base)

    def _guess_assets(self):
        cand = os.path.join(os.path.dirname(os.path.abspath(self.b.path)),
                            self._default_vendor_id())
        return cand if os.path.isdir(cand) else None

    def _build_models(self):
        models = collections.OrderedDict()
        for mid, meta in self.b.printer_models().items():
            models[mid] = VendorModel(mid, meta)
        for name in self.b.names('printer'):
            pv = PrinterVariant(name, self.b.resolve('printer', name))
            if pv.model not in models:
                models[pv.model] = VendorModel(pv.model, {'name': pv.model})
            models[pv.model].variants.append(pv)
        return collections.OrderedDict(
            (k, v) for k, v in models.items() if v.variants)

    def _warn_multi_tool(self):
        for model in self.models.values():
            if model.is_toolchanger:
                self.conv.note(f'printer {model.id}: converted as a '
                               f'{model.extruders}-tool changer')
            elif model.is_mmu:
                self.conv.note(f'printer {model.id}: converted as one tool fed by a '
                               f'{model.extruders}-slot MMU feeder')

    # -- compatibility ----------------------------------------------------- #
    def matching_variants(self, kind, name):
        """Which (model, PrinterVariant) pairs a preset applies to."""
        how, what = self.b.compat(kind, name)
        if how == 'list':
            # Orca names the compatible machine presets outright
            wanted = set(what)
            return [(m, pv) for m in self.models.values() for pv in m.variants
                    if pv.preset_name in wanted]
        condition = what
        cached = self._cond_cache.get(condition)
        if cached is not None:
            return cached
        hits = []
        for model in self.models.values():
            for pv in model.variants:
                try:
                    if ConditionEvaluator(pv.values, self.missing_keys).evaluate(condition):
                        hits.append((model, pv))
                except ValueError as e:
                    self.conv.note(f'condition not understood ({e}); '
                                   f'treated as compatible')
                    hits.append((model, pv))
        self._cond_cache[condition] = hits
        return hits

    def condition_for(self, hits):
        """Render matching (model, variant) pairs as a 3.x condition."""
        if not hits:
            return None
        by_model = collections.OrderedDict()
        for model, pv in hits:
            by_model.setdefault(model.id, set()).add(pv.tool)
        # Always name the models explicitly.  A 2.x bundle is its own world, so a
        # preset compatible with every printer in it needs no condition there -
        # but converted bundles share one 3.x vendor, and an unconditioned preset
        # would then be offered for every other vendor's printers too.
        # Group the models that end up with the same tool clause, so a preset
        # shared by a dozen variants of one machine reads as one term.
        groups = collections.OrderedDict()
        for mid, tools in by_model.items():
            groups.setdefault(self._tool_clause(mid, tools), []).append(mid)
        terms = []
        for clause, mids in groups.items():
            models = ' or '.join(f'printer.model == "{m}"' for m in mids)
            if len(mids) > 1:
                models = f'({models})'
            terms.append(models if not clause else f'({models} and {clause})')
        return terms[0] if len(terms) == 1 else ' or '.join(terms)

    def _tool_clause(self, mid, tools):
        """The tool half of a condition, empty when every tool matches."""
        all_tools = self.models[mid].tools
        if set(tools) == set(all_tools):
            return ''
        mixed_flow = len({t.high_flow for t in all_tools}) > 1
        parts = []
        for t in sorted(tools):
            p = f'tool.nozzle_diameter == {t.nozzle:g}'
            if mixed_flow:
                p += ' and tool.nozzle_high_flow' if t.high_flow \
                     else ' and ! tool.nozzle_high_flow'
                p = f'({p})'
            parts.append(p)
        return parts[0] if len(parts) == 1 else '(' + ' or '.join(parts) + ')'

    # -- printer-level options that moved into print presets --------------- #
    def moved_printer_keys(self, pv):
        """2.x printer options that 3.x keeps on the print/tool preset."""
        out = collections.OrderedDict()
        printer_pool = self.schema.by_kind['printer']
        for k, raw in pv.values.items():
            if k in META_KEYS or k in printer_pool:
                continue
            if k in self.schema.print_pool:
                out[k] = raw
        return out

    # -- emission ---------------------------------------------------------- #
    def emit(self, outdir):
        vdir = os.path.join(outdir, self.vendor_id, self.version)
        if os.path.isdir(outdir):
            shutil.rmtree(outdir)
        os.makedirs(vdir)
        tag = slug(self.vendor_id).lower()

        n_print = self._emit_prints(vdir, tag)
        self._emit_tool_print(vdir, tag)
        n_fil = self._emit_filaments(vdir)
        self._emit_printer(vdir, tag)
        self._emit_vendor(vdir)
        self._emit_fragment(outdir)
        n_assets = self._copy_assets(vdir)
        self._emit_repository(outdir, vdir)
        skipped = self._skipped_kinds()
        return {'models': len(self.models), 'print_presets': n_print,
                'filament_presets': n_fil, 'assets': n_assets,
                'skipped_kinds': skipped, 'vendor_dir': vdir}

    def _skipped_kinds(self):
        out = {}
        for kind in ('sla_print', 'sla_material', 'physical_printer'):
            n = len([s for s in getattr(self.b, 'sections', ())
                     if s.startswith(kind + ':')])
            if n:
                out[kind] = n
                self.conv.note(f'{kind}: {n} preset(s) skipped '
                               f'(ps2to3 converts FFF presets only)')
        return out

    def _emit_prints(self, vdir, tag):
        docs = []
        for name in self.b.names('print'):
            kv = self.b.resolve('print', name)
            hits = self.matching_variants('print', name)
            self.print_meta[name] = [(m.id, pv.tool) for m, pv in hits]
            if not hits:
                self.skipped.append(('print', name))
                continue
            moved = {}
            for _m, pv in hits:
                for k, v in self.moved_printer_keys(pv).items():
                    moved.setdefault(k, v)
            vals = self.conv.values(kv, 'print', extra_moves=moved)
            doc = ['kind: print', f'id: {mkid(self.vendor_id + "/print/" + name)}',
                   f'name: {yscalar(name)}']
            cond = self.condition_for(hits)
            if cond:
                doc.append(f'condition: {cond}')
            doc.append('values:')
            doc += yvalues(vals, 2)
            docs.append('\n'.join(doc))
        if docs:
            files.write(os.path.join(vdir, f'preset-print-{tag}.yaml'),
                        '\n---\n'.join(docs) + '\n')
        return len(docs)

    def _emit_tool_print(self, vdir, tag):
        # One variant per printer model: a single variant whose condition matches
        # several models resolves for only one of them, and selecting any other
        # then dies in preset evaluation.
        lines = ['kind: tool_print', f'id: common {self.vendor_id}', 'variants:']
        for mid in self.models:
            lines += [f'- condition: printer.model == "{mid}"',
                      f'  name: no tool {mid}',
                      f'  id: {mkid(self.vendor_id + "/tool/" + mid)}']
        files.write(os.path.join(vdir, f'preset-tool-{tag}.yaml'),
                    '\n'.join(lines) + '\n')

    def _emit_filaments(self, vdir):
        n = 0
        for name in self.b.names('filament'):
            kv = self.b.resolve('filament', name)
            hits = self.matching_variants('filament', name)
            if not hits:
                self.skipped.append(('filament', name))
                continue
            if kv.get('compatible_prints_condition', '').strip():
                self.conv.note('filament: 2.x limited this filament to certain print '
                               'presets via their `notes`; 3.x has no equivalent '
                               'condition, so the limit is dropped')
            vals = self.conv.values(kv, 'filament')
            ftype = kv.get('filament_type', '').strip()
            doc = ['kind: filament', f'id: {yscalar(name)}', f'name: {yscalar(name)}']
            if ftype:
                doc.append('features:')
                doc.append(f'  $.type: {yscalar(ftype)}')
                if kv.get('filament_abrasive', '0').strip() in ('1', 'true'):
                    doc.append('  $.tags: [abrasive]')
            cond = self.condition_for(hits)
            if cond:
                doc.append(f'condition: {cond}')
            doc.append('values:')
            doc += yvalues(vals, 2)
            fn = f'preset-filament-{slug(ftype) or "X"}-{slug(name)}.yaml'
            files.write(os.path.join(vdir, fn), '\n'.join(doc) + '\n')
            n += 1
        return n

    def _default_print_for(self, model, tool):
        explicit = None
        for pv in model.variants:
            if pv.tool == tool:
                explicit = pv.values.get('default_print_profile')
                break
        if explicit and explicit in self._known('print'):
            return explicit
        cands = [n for n, pairs in self.print_meta.items()
                 if (model.id, tool) in pairs]
        return cands[0] if cands else None

    def _default_material_for(self, model):
        mats = self.b.printer_models().get(model.id, {}).get('default_materials', '')
        first = [m.strip() for m in mats.split(';') if m.strip()]
        known = self._known('filament')
        if first and first[0] in known:
            return first[0]
        for pv in model.variants:
            cand = pv.values.get('default_filament_profile')
            if cand and cand in known:
                return cand
        return None

    def _known(self, kind):
        if kind not in self._known_cache:
            self._known_cache[kind] = set(self.b.names(kind))
        return self._known_cache[kind]

    def _fix_multi_material_flags(self, vals, model):
        """Make single_extruder_multi_material agree with the hardware emitted.

        It means one hotend fed from several sources, so it belongs to an MMU and
        nothing else.  Orca's common machine base sets it on every printer,
        including single-extruder ones, and 3.x then tries to build purge data
        for extruders that do not exist.
        """
        want = model.is_mmu
        if vals.get('single_extruder_multi_material', want) != want:
            self.conv.note(
                f'printer {model.id}: single_extruder_multi_material was '
                f'{str(vals["single_extruder_multi_material"]).lower()} in the '
                f'source; set to {str(want).lower()} to match the '
                + ('MMU feeder' if want else
                   'tool changer' if model.is_toolchanger else 'single tool')
                + ' this converts to')
        vals['single_extruder_multi_material'] = want
        return vals

    @staticmethod
    def _fit_per_tool_arrays(vals, extruders):
        """Give per-extruder printer arrays one entry per tool.

        3.x rejects a printer whose extruder_offset is shorter than its tool
        count, and a 2.x bundle often leaves it unset on a multi-tool printer
        because 2.x filled the gap from the default.
        """
        if extruders <= 1:
            return vals
        cur = vals.get('extruder_offset') or ['0x0']
        if len(cur) < extruders:
            vals['extruder_offset'] = cur + [cur[-1]] * (extruders - len(cur))
        return vals

    def _emit_printer(self, vdir, tag):
        lines = [f'id: {mkid(self.vendor_id + "/printer/root")}', 'kind: printer',
                 'variants:']
        for model in self.models.values():
            base_pv = model.variants[0]
            base_vals = self.conv.values(
                {k: v for k, v in base_pv.values.items()
                 if k not in self.schema.print_pool or k in self.schema.by_kind['printer']},
                'printer')
            base_vals = self._fit_per_tool_arrays(base_vals, model.extruders)
            base_vals = self._fix_multi_material_flags(base_vals, model)
            lines.append(f'- condition: printer.model == "{model.id}"')
            lines.append(f'  name: {yscalar(model.display)}')
            lines.append(f'  id: {mkid(self.vendor_id + "/printer/" + model.id)}')
            lines.append('  values:')
            lines += yvalues(base_vals, 6)
            lines.append('  variants:')
            for tool in model.tools:
                pv = next(v for v in model.variants if v.tool == tool)
                own = self.conv.values(
                    {k: v for k, v in pv.values.items()
                     if k not in self.schema.print_pool or k in self.schema.by_kind['printer']},
                    'printer')
                own = self._fix_multi_material_flags(own, model)
                vals = collections.OrderedDict(
                    (k, v) for k, v in own.items() if base_vals.get(k) != v)
                dp = self._default_print_for(model, tool)
                if dp:
                    vals['default_print'] = dp
                cond = f'tool.nozzle_diameter == {tool.nozzle:g}'
                if len({t.high_flow for t in model.tools}) > 1:
                    cond += ' and tool.nozzle_high_flow' if tool.high_flow \
                            else ' and ! tool.nozzle_high_flow'
                lines.append(f'  - condition: {cond}')
                lines.append(f'    id: {mkid(self.vendor_id + f"/printer/{model.id}/{tool.tid}")}')
                lines.append('    values:')
                lines += yvalues(vals, 6)
        files.write(os.path.join(vdir, f'preset-printer-{tag}.yaml'),
                    '\n'.join(lines) + '\n')

    def _printer_features(self, model):
        # Every supports_*_nozzle is false on purpose: the conversion brings its
        # own tool docs (see _tool_docs), and leaving these true would also offer
        # the host vendor's identically-sized tools on a merged printer.
        out = [('supports_high_flow_nozzle', 'false'),
               ('input_shaper', 'false'), ('planetary_gearbox', 'false'),
               ('supports_tool_preheating', 'false'),
               ('multi_extruder', 'true' if model.is_toolchanger else 'false'),
               ('bed_segments_x', '1'), ('bed_segments_y', '1')]
        for feat in list(NOZZLE_FEATURE.values()) + [
                'supports_mmu_025_nozzle', 'supports_mmu_03_nozzle',
                'supports_mmu_04_nozzle', 'supports_mmu_05_nozzle',
                'supports_mmu_06_nozzle', 'supports_mmu_08_nozzle']:
            out.append((feat, 'false'))
        return out

    def _visual(self, model):
        """Only reference assets that are actually present.

        A vendor bundle can name a bed model whose file was never shipped - the
        2.x Positron3D bundle names bedmodel_prusawire.stl and does not include
        it - and 3.x crashes when the UI tries to load the missing file, where
        the CLI merely logs.
        """
        out = []
        for field in ('bed_model', 'bed_texture', 'thumbnail'):
            v = self.visual_override.get(field) or model.meta.get(field)
            if not v:
                continue
            if self.assets_dir and os.path.isfile(os.path.join(self.assets_dir, v)):
                out.append(f'  {field}: {v}')
            else:
                self.conv.note(f'printer {model.id}: {field} names {v!r}, which is '
                               f'not among the assets; dropped, because 3.x crashes '
                               f'on a missing asset')
        return (['visual:'] + out) if out else []

    def tool_ref(self, tool):
        """Namespaced tool id.

        `install --mode merge` puts the conversion inside another vendor, whose
        tool ids ('0.4', '0.4HF', ...) would otherwise collide - and whose tool
        set may not even contain the nozzle we need: Prusa declares no 0.2 mm
        nozzle, which a Snapmaker needs.
        """
        return f'{slug(self.vendor_id).lower()}-{tool.tid}'

    def _tool_docs(self):
        """One tool doc per distinct nozzle, offered only to our own printers."""
        docs = []
        for tool in self._all_tools():
            users = [m.id for m in self.models.values() if tool in m.tools]
            cond = ' or '.join(f'printer.model == "{m}"' for m in users)
            d = ['kind: tool', 'technology: FFF', f"id: '{self.tool_ref(tool)}'",
                 f"name: '{tool.label}'", f'condition: {cond}', 'features:',
                 '  nozzle_diameter:', f'    default: {tool.nozzle:g}']
            if tool.high_flow:
                d += ['  nozzle_high_flow:', '    default: true']
            docs.append('\n'.join(d))
        return docs

    def _printer_docs(self, sheet_id):
        """The tool, printer, feeder and printer_config docs.

        Shared by vendor.yaml and the merge fragment.
        """
        docs = list(self._tool_docs())
        for model in self.models.values():
            d = ['kind: printer', f'technology: {model.technology}',
                 f'name: {yscalar(model.display)}', f'id: {slug(model.id).lower()}',
                 'model:', f'  base_model: {model.id}', f'  model: {model.id}',
                 f'tool_count: {model.extruders if model.is_toolchanger else 1}',
                 'features:']
            for feat, val in self._printer_features(model):
                d += [f'  {feat}:', f'    default: {val}']
            d += self._visual(model)
            docs.append('\n'.join(d))
        # 3.x models an MMU as a feeder with several slots in front of one tool
        for model in self.models.values():
            if not model.is_mmu:
                continue
            docs.append('\n'.join([
                'kind: feeder', 'technology: FFF', f'id: {model.feeder_id}',
                f'name: {yscalar(model.display + " feeder")}',
                f'condition: printer.base_model == "{model.id}"',
                'feeder_type: mmu', 'model:',
                f'  base_model: {slug(model.id).upper()}_FEEDER',
                f'  model: {slug(model.id).upper()}_FEEDER',
                f'slot_count: {model.extruders}']))
        for model in self.models.values():
            default_tool = model.tools[0]
            d = ['kind: printer_config', f'id: {slug(model.id).lower()}-cfg',
                 f'name: {yscalar(model.display)}',
                 f'printer: {slug(model.id).lower()}',
                 f'legacy_printer_model: [{model.id}]']
            if model.is_toolchanger:
                d.append(f'tool_count: {model.extruders}')
            elif not model.is_mmu:
                d.append('tool_count: 1')
            d += ['tools:', f"- tool: '{self.tool_ref(default_tool)}'"]
            if model.is_mmu:
                d += ['feeders:', f'- feeder: {model.feeder_id}', '  address: [0]']
            d.append(f'sheet: {sheet_id}')
            docs.append('\n'.join(d))
        return docs

    def _all_tools(self):
        seen, out = set(), []
        for model in self.models.values():
            for t in model.tools:
                if t.tid not in seen:
                    seen.add(t.tid)
                    out.append(t)
        return out

    def _emit_vendor(self, vdir):
        parts = ['\n'.join([
            'kind: vendor', f'id: {self.vendor_id}', f'name: {yscalar(self.vendor_name)}',
            f'version: {self.version}', 'features:', '  printer:',
            '    supports_high_flow_nozzle:', '      default: false',
            '      user_editable: false',
            '    input_shaper:', '      default: false', '      user_editable: false',
            '    planetary_gearbox:', '      default: false', '      user_editable: false',
            '    supports_tool_preheating:', '      default: false',
            '    multi_extruder:', '      default: false',
            '    bed_segments_x:', '      default: 1',
            '    bed_segments_y:', '      default: 1',
            '    auxiliary_travel_anchor_x:', '      default: -1',
            '    auxiliary_travel_anchor_y:', '      default: -1',
        ] + sum([[f'    {f}:', '      default: false']
                 for f in list(NOZZLE_FEATURE.values()) +
                 ['supports_mmu_025_nozzle', 'supports_mmu_03_nozzle',
                  'supports_mmu_04_nozzle', 'supports_mmu_05_nozzle',
                  'supports_mmu_06_nozzle', 'supports_mmu_08_nozzle']], []) + [
            '  tool:',
            '    nozzle_high_flow:', '      default: false', '      user_editable: false',
            '    nozzle_diameter:', '      default: 0.4', '      user_editable: false',
            '  sheet:',
            '    cold:', '      default: false', '      user_editable: false',
            '  feeder:',
            '    single_mode:', '      default: false',
        ])]
        parts.append('\n'.join(['kind: sheet', 'id: pei_smooth', 'name: PEI Smooth',
                                'type: pei_smooth']))
        parts += self._printer_docs('pei_smooth')
        files.write(os.path.join(vdir, 'vendor.yaml'), '\n---\n'.join(parts) + '\n')

    def _emit_fragment(self, outdir):
        """Docs to append to another vendor's vendor.yaml (see MERGE_VENDOR)."""
        header = [
            '# printer and printer_config docs for '
            f'{self.vendor_name} ({self.vendor_id}), converted by ps2to3.',
            '# Tools and sheets are the host vendor\'s; only the printers are added.']
        docs = self._printer_docs('pei_smooth')
        text = '\n'.join(header) + '\n---\n' + '\n---\n'.join(docs) + '\n'
        files.write(os.path.join(outdir, 'vendor-fragment.yaml'), text)

    def _copy_assets(self, vdir):
        adir = os.path.join(vdir, 'assets')
        os.makedirs(adir, exist_ok=True)
        if not self.assets_dir:
            wanted = {model.meta.get(f) for model in self.models.values()
                      for f in ('bed_model', 'bed_texture', 'thumbnail')} - {None}
            if wanted:
                self.conv.note('assets: bed model/texture/thumbnail not found '
                               '(pass --assets DIR); the printer will have no bed mesh')
            return 0
        n = 0
        for f in sorted(os.listdir(self.assets_dir)):
            src = os.path.join(self.assets_dir, f)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(adir, f))
                n += 1
        return n

    def _emit_repository(self, outdir, vdir):
        entries = []
        for root, _dirs, fns in os.walk(vdir):
            for fn in sorted(fns):
                p = os.path.join(root, fn)
                with open(p, 'rb') as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
                entries.append({'filename': os.path.relpath(p, vdir).replace(os.sep, '/'),
                                'filehash': digest})
        entries.sort(key=lambda d: d['filename'])
        files.write_json(os.path.join(vdir, 'manifest.json'), entries)

        idx = f'min_slic3r_version = 3.0.0-alpha0\n{self.version} Converted by ps2to3\n'
        with zipfile.ZipFile(os.path.join(outdir, 'vendor_indices.zip'), 'w',
                             zipfile.ZIP_DEFLATED) as z:
            z.writestr(self.vendor_id + '.idx', idx)
        # NB: a repository's manifest.json is a single object, unlike the
        # data directory's RepositoryManifest.json, which is an array.
        manifest = {
            'name': self.vendor_name,
            'description':
                f'{self.vendor_name} profiles converted from PrusaSlicer 2.x',
            'visibility': '',
            'id': self.repo_id,
            'version': 2,
            'url': f'http://localhost:8000/v2/repos/{self.repo_id}',
            'index_url':
                f'http://localhost:8000/v2/repos/{self.repo_id}/vendor_indices.zip',
        }
        files.write_json(os.path.join(outdir, 'manifest.json'), manifest)
