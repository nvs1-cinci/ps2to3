"""the printer, tool and feeder shapes a 3.x vendor describes."""

from __future__ import annotations

import collections

from .conditions import _as_num
from .emit import slug

NOZZLE_FEATURE = {0.25: 'supports_025_nozzle', 0.3: 'supports_03_nozzle',
                  0.4: 'supports_04_nozzle', 0.5: 'supports_05_nozzle',
                  0.6: 'supports_06_nozzle', 0.8: 'supports_08_nozzle'}


class Tool(collections.namedtuple('Tool', 'nozzle high_flow')):
    @property
    def tid(self):
        return f'{self.nozzle:g}HF' if self.high_flow else f'{self.nozzle:g}'

    @property
    def label(self):
        return f'{self.nozzle:g} HF' if self.high_flow else f'{self.nozzle:g}'


class PrinterVariant:
    """One 2.x printer preset: a (model, tool) pair plus its values."""

    def __init__(self, preset_name, values):
        self.preset_name = preset_name
        self.values = values
        self.model = values.get('printer_model') or preset_name
        nozzles = [p for p in values.get('nozzle_diameter', '').split(',') if p.strip()]
        noz = _as_num(nozzles[0]) if nozzles else None
        hf = values.get('nozzle_high_flow', '0').split(',')[0].strip() in ('1', 'true')
        self.tool = Tool(noz or 0.4, hf)
        # 2.x describes an MMU or a tool-changer as one printer with several
        # extruders; 3.x splits that into a feeder or a multi-tool printer_config,
        # neither of which this converter builds.
        self.extruders = max(1, len(nozzles))
        self.mmu = values.get('single_extruder_multi_material', '0').strip() in ('1', 'true')


class VendorModel:
    """A 3.x printer: one 2.x printer_model and the tools it supports."""

    def __init__(self, model_id, meta):
        self.id = model_id
        self.meta = meta
        self.display = meta.get('name') or model_id
        self.variants = []            # PrinterVariant, in bundle order

    @property
    def tools(self):
        seen, out = set(), []
        for v in self.variants:
            if v.tool not in seen:
                seen.add(v.tool)
                out.append(v.tool)
        return out

    @property
    def technology(self):
        return (self.meta.get('technology') or 'FFF').upper()

    @property
    def extruders(self):
        return max(v.extruders for v in self.variants)

    @property
    def is_mmu(self):
        """One extruder fed from several slots (MMU / MMU-like)."""
        return any(v.mmu for v in self.variants) and self.extruders > 1

    @property
    def is_toolchanger(self):
        """Several independent tools (tool changer / IDEX)."""
        return self.extruders > 1 and not self.is_mmu

    @property
    def feeder_id(self):
        return slug(self.id).lower() + '-feeder'
