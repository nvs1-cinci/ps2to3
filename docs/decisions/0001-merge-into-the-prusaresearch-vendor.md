# ADR-0001: merge conversions into the PrusaResearch vendor

- status: accepted
- date: 2026-08-31
- deciders: repo owner

## context

prusaslicer 3.x replaced 2.x's single-ini vendor bundle with a directory of yaml
preset documents served from a preset repository. a converted vendor is therefore
a repository: `manifest.json`, `vendor_indices.zip`, and `<Vendor>/<version>/`
holding `vendor.yaml` plus one document per preset.

3.0.0-alpha10 accepts such a repository (`--preset-update-add-local`) and then
ignores every vendor in it whose id is not `PrusaResearch`. the guard is in the
binary:

```
ASSERT(... || strcmp(vendor, "PrusaResearch") != 0)   PresetInteractor.cpp:283
```

so a correctly built repository for any other vendor installs, reports success,
and produces no printers. patching that out is not available either: the 3.x
source is not published (github tops out at `version_2.9.6`), the linux binary is
stripped, and the windows build ships no pdbs.

## decisions

chosen: inject the converted documents **into** the shipped PrusaResearch vendor
directory, and append the printer and printer_config documents to its
`vendor.yaml` between markers.

- a separate vendor directory was rejected because alpha10 does not read one
- a local repository install (`--mode repo`) is kept, because it is the shape the
  release is expected to accept, but it is not the default
- patching the binary was rejected for now: the literal is locatable but the
  patch would have to be re-derived for every alpha build

each injection records its own file list (`.ps2to3-<vendor>.files`) so removing
one conversion cannot touch prusa's files or another conversion's.

## consequences

- converted printers appear in the wizard beside prusa's own, and slice
- every converted preset needs an explicit `printer.model` condition: it now
  shares a vendor with prusa's presets, and an unconditioned preset would be
  offered for prusa printers too
- tool documents have to be namespaced (`acme-0.4`), because the host vendor
  already declares tools of its own
- a preset update replaces the whole PrusaResearch directory and silently takes
  the injected printers with it. that forced the registry outside the vendor
  (`<datadir>/ps2to3-installed.json`) and the `restore` command
- uninstall is surgical rather than "delete the directory"
