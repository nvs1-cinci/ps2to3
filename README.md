# ps2to3

by [nomadsgalaxy](https://nomadsgalaxy.com). licensed under
[OCL v1.1 + SWAtt v1](LICENSE) (open community license, software attribution):
use it, change it, hack it, and if you pass a derivative on, keep the
attribution visible in its interface and its source. not affiliated with,
endorsed by, or supported by prusa research.

converts printer profiles into the prusaslicer 3.x yaml preset format, so a
profile that only exists for 2.x, orcaslicer or bambu studio can be tested on 3.x
before anyone publishes a 3.x repository for it. 2.x ships a vendor as one `.ini`;
3.x replaced that with a directory of yaml presets served from a preset
repository, and moved a lot around on the way: options changed type, per-extruder
vectors became per-tool presets, nozzle diameters became hardware features instead
of preset variants, and preset compatibility is a `printer.model` /
`tool.nozzle_diameter` condition instead of a `printer_notes` regex. this tool
does that translation and says what it could not carry across.

## read this first

prusaslicer 3 is an early alpha preview, and prusa is only focused on testing it
with included printers, the current consumer prusa lineup. this is a quick and
dirty way to add non-prusa printers to it and **is not meant to be official in any
capacity**. third-party printer support will arrive later, once the app is more
stable and prusa builds it properly. there are no guarantees or promises here and
this is likely to break something.

a converted profile is a translation, not a copy. options whose units or meaning
changed are dropped rather than guessed, settings that only exist in the source
slicer are dropped, and custom g-code is rewritten where the old placeholders no
longer exist. every one of those decisions is printed as a conversion note. check
the g-code before you trust it, and keep the 2.x install for real work.

**if prusaslicer 3 crashes with a converted printer selected, do not report it as
a bug to prusa.** remove the converted printers, restart, and try to reproduce the
same bug using only the profiles the alpha shipped with. if it still happens on
stock profiles it is a real bug worth submitting, and say which stock printer it
reproduced on. if it only happens with a converted profile, it is this tool's
problem, not prusa's.

the importer shows this as a modal that has to be acknowledged before it will do
anything, and `install` prints a short form unless `-y` is passed.

## links

| what | where |
|---|---|
| prusaslicer 2.x profiles | `~/.config/PrusaSlicer/vendor/*.ini` (see `ps2to3 paths`) |
| orcaslicer profiles | https://github.com/OrcaSlicer/OrcaSlicer `resources/profiles` |
| snapmaker's orca fork | https://github.com/Snapmaker/OrcaSlicer |
| bambu studio profiles | https://github.com/bambulab/BambuStudio `resources/profiles` |
| positron and prusawire profiles | https://github.com/Positron3D |
| decisions behind the tool | [docs/decisions](docs/decisions) |
| how to work on it | [CONTRIBUTING.md](CONTRIBUTING.md) |
| changes | [docs/CHANGELOG.md](docs/CHANGELOG.md) |

## commands

| command | does |
|---|---|
| `make venv` | create `.venv` and install the package for development |
| `make test` | run the test suite |
| `make lint` | ruff |
| `make preflight` | lint and test, everything that must pass before a commit |
| `make run` | open the importer window |
| `make dist` | build `dist/ps2to3-<version>.zip` to hand to somebody else |
| `ps2to3 paths` | what this machine looks like to the tool |
| `ps2to3 schema` | export the 3.x option schema from a local prusaslicer |
| `ps2to3 convert SOURCE` | convert a profile source to a 3.x repository |
| `ps2to3 verify SOURCE BUILD` | compare a conversion against its source |
| `ps2to3 install BUILD` | install a conversion into a data directory |
| `ps2to3 restore` | reinstall what a prusaslicer preset update removed |
| `ps2to3 uninstall [VENDOR]` | remove one conversion, or list what is installed |

## environment

| var | required | default | description |
|---|---|---|---|
| `PS2TO3_DATADIR` | no | discovered | prusaslicer 3 data directory to use. wins over discovery even before it exists |
| `PS2TO3_SLICER` | no | discovered | how to run prusaslicer 3, as a command line. only needed to export the schema |

nothing else is configurable by environment, and nothing is hardcoded to one
machine: data directories, installed 2.x bundles and prusaslicer itself are found
from the platform's own conventions and then validated on disk (ADR-0004).
`ps2to3 paths` prints every candidate, where it came from, and its state.

## key files

| path | purpose |
|---|---|
| `src/ps2to3/bundle.py` | reads the three source shapes: 2.x ini, orca/bambu index, 3mf |
| `src/ps2to3/orca.py` | orca/bambu json, presented as a 2.x bundle |
| `src/ps2to3/orca_script.py` | orca's custom-g-code dialect, translated to 3.x placeholders |
| `src/ps2to3/conditions.py` | evaluates 2.x compatibility expressions per printer |
| `src/ps2to3/values.py` | option-by-option value conversion against the schema |
| `src/ps2to3/gcode.py` | custom g-code placeholder migration |
| `src/ps2to3/hardware.py` | printer, tool and feeder shapes derived from the source |
| `src/ps2to3/convert.py` | emits the repository |
| `src/ps2to3/emit.py` | yaml scalars, block scalars and preset ids |
| `src/ps2to3/install.py` | installing, uninstalling, the registry, restore |
| `src/ps2to3/verify.py` | reads a conversion back and compares it to the source |
| `src/ps2to3/paths.py` | per-platform discovery of everything on disk |
| `src/ps2to3/schema.py` | the 3.x option schema, shipped, cached or exported |
| `src/ps2to3/gui/` | the importer window |
| `src/ps2to3/schema.json` | the shipped schema, so the tool works with no prusaslicer installed |

## the importer

double-click and go. nothing to install beyond python, and closing the window ends
the process.

| platform | file |
|---|---|
| linux | `ps2to3-importer.sh`, or the `.desktop` file |
| macos | `ps2to3 importer.command` |
| windows | `ps2to3 importer.cmd` |

the window takes a profile source, a bed texture, a bed model and a printer image,
converts, shows what it could and could not carry across, and either saves the 3.x
repository as a zip or installs it into a data directory. the data directory is a
dropdown filled from discovery, and the 2.x bundles already installed are offered
as sources.

it is tkinter, which ships with python, so there is no browser and nothing to
fetch (ADR-0003). the conversion path is standard library only, so the launchers
work on a plain python; pyyaml is needed only by `verify`.

it is styled to look like the app it converts profiles for. the palette is not
invented: `src/ps2to3/gui/theme.py` names the prusaslicer 3 resource each colour
comes from, `#ED6B21` being the orange in 433 of the icons the slicer ships. it
opens in the desktop's own light or dark preference and the button in the top
right switches, and it asks for Inter, the ui font prusaslicer ships, falling back
to the platform's own.

it sizes itself to the screen it opens on: never larger than the display, a
vertical scrollbar that appears only when the form is taller than the window, and
hint text that rewraps as the width changes. the minimum window size is measured
from the form itself, so the window cannot be made narrow enough to clip anything.

## handing it to somebody else

```bash
make dist          # dist/ps2to3-0.2.0.zip
```

the zip holds the app, the launchers and the documentation: no venv, no build
output, no tests, and none of the vendor artwork under `assets/`, which is other
people's files. it unpacks to one folder, and the person who gets it
double-clicks the launcher for their platform. nothing to install, because the
conversion path is standard library only.

the build is reproducible (every entry carries a fixed timestamp and the entries
are sorted), so the same source gives the same bytes and a changed checksum means
changed content. `verify` needs pyyaml, which a plain python may not have:
`pip install pyyaml`, or `pip install -e '.[verify]'` from the unpacked folder.

## converting from the command line

```bash
make venv                       # .venv with the package installed
.venv/bin/ps2to3 paths          # what this machine has

.venv/bin/ps2to3 convert ~/.config/PrusaSlicer/vendor/PrusaProHT.ini \
    --vendor-id PrusaProHT \
    --assets    ~/.config/PrusaSlicer/vendor/PrusaProHT \
    --output    build/PrusaProHT

.venv/bin/ps2to3 verify ~/.config/PrusaSlicer/vendor/PrusaProHT.ini build/PrusaProHT
.venv/bin/ps2to3 install build/PrusaProHT
```

`install` finds the data directory itself; `--datadir` overrides it. the schema
comes from the copy shipped in the package, so `ps2to3 schema` is only needed to
convert against a newer alpha than the one that copy came from.

input can be a **vendor bundle** (`[vendor]` plus `[printer_model:...]`
sections), a **config bundle** exported from the 2.x gui (printer models are
synthesised from the printer presets' `printer_model`), an **orca or bambu vendor
index** (`.json`), or a **3mf**. a 3mf stores its whole resolved configuration, so
it converts as one printer with one print and one filament preset.

## what convert produces

```
build/PrusaProHT/
  manifest.json                     repository descriptor (a single json object)
  vendor_indices.zip                contains <VendorId>.idx
  vendor-fragment.yaml              printer docs for install --mode merge
  <VendorId>/<version>/
    vendor.yaml                     vendor, printers, tools, sheet, printer_configs
    preset-printer-<vendor>.yaml    one variant per model, nested per nozzle
    preset-print-<vendor>.yaml      one doc per 2.x print preset
    preset-tool-<vendor>.yaml       one tool_print variant per model
    preset-filament-*.yaml          one file per 2.x filament preset
    assets/                         bed model, bed texture, thumbnail
    manifest.json                   {filename, sha256} for every file above
```

## install modes

`--mode merge` (default) appends the converted printers to the `PrusaResearch`
vendor already in the data directory and drops the preset files beside it. it is
idempotent, re-running replaces the previous injection, and it is the only mode
that currently works, because 3.0.0-alpha10 only wires up the vendor whose id is
`PrusaResearch`. any other vendor loads, and its printers never reach the ui. the
guard is visible in the binary as

```
ASSERT(vendor_bundle_it != preset_bundle.vendor_bundles.end()
       || strcmp(vendor, "PrusaResearch") != 0)   PresetInteractor.cpp:283
```

the reasoning, and what it costs, is ADR-0001.

a prusaslicer preset update replaces the whole `PrusaResearch` vendor directory
and silently takes every injected printer with it. what was installed is recorded
in `<datadir>/ps2to3-installed.json`, which lives outside the vendor and so
survives, and

```bash
.venv/bin/ps2to3 restore
```

puts them all back. the importer has the same thing as a button. `uninstall` with
no vendor id lists what is installed and flags anything an update removed.

`--mode repo` packages the conversion as a local repository and registers it with
`--preset-update-add-local`. the registration succeeds today and the vendor stays
invisible for the reason above. it is here for when that changes.

## things worth knowing about the 3.x format

learned the hard way. each one silently produces nothing rather than an error.

- **preset ids must be base64-encoded uuidv4.** every id in prusa's own bundle is
  a v4 with the rfc-4122 variant bits. 22 random base64 characters are rejected
- **a repository's `manifest.json` is a single json object**, unlike the data
  directory's `RepositoryManifest.json`, which is an array
- **each printer model needs its own `tool_print` preset variant.** one variant
  whose condition matches several models resolves for only one of them, and
  picking any other then dies with `vector::_M_range_check ... (which is 0)`
- **a vendor directory's name must equal the vendor's `id`** or the app asserts
- printer profile names are `<printer_config name> <tool name>`, and only the
  printer_config's default tool is addressable from the cli. other nozzles are
  chosen in the gui's printer settings

## multi-material

2.x describes both an mmu and a tool changer as one printer with several
extruders. 3.x splits them: a tool changer is a `printer_config` with
`tool_count: N`, an mmu is one tool behind a `feeder` with `slot_count: N`. the
converter reads `single_extruder_multi_material` and the length of
`nozzle_diameter` to tell them apart and emits the right shape, including
`multi_extruder` on the printer and one `extruder_offset` entry per tool. 3.x
rejects a printer whose offsets are shorter than its tool count, and 2.x often
left that unset.

where 2.x has several printer presets for one nozzle, the mmu and non-mmu variants
of the same machine for instance, only the first survives, and `verify` lists the
ones it had to leave out.

## custom g-code placeholders

3.x removed some 2.x placeholders. `convert` renames the ones with a direct
counterpart, verified by slicing a probe g-code against 3.0.0-alpha10:

| 2.x | 3.x |
|---|---|
| `printer_preset` | `printer_settings_id` |
| `print_preset` | `print_settings_id` |
| `filament_preset` | `filament_settings_id` |
| `physical_printer_preset` | gone |

a preset whose g-code uses `physical_printer_preset` will not export at all, so it
is reported, and `--fix-gcode` neutralises it: interpolations print nothing and
`{if physical_printer_preset =~ /.../}` comparisons see an empty string, which is
how they would read with no physical printer selected. snapmaker's profiles need
this.

## assets

printer artwork (bed models, bed textures, thumbnails) is not in this repository:
those files belong to the printer's vendor and are not ours to redistribute. take
them from the source you are converting - a 2.x vendor bundle ships them beside
its `.ini`, an orca vendor tree ships them under its own directory - and point
`--assets` at that directory. `--bed-model`, `--bed-texture` and `--thumbnail`
name individual files for a source that names none.

a config bundle records the custom bed as an absolute path on the machine that
exported it, `C:\Positron_bed.stl`, which overrides the vendor's bed model and
points at nothing. `convert` clears `bed_custom_model` and `bed_custom_texture`
when the file is not there.

a vendor bundle can also name a bed model whose file it never shipped. the 2.x
positron3d bundle names `bedmodel_prusawire.stl` and does not include it, and 3.x
is unhappy loading a missing asset, so `convert` drops references to files that
are not in `--assets` and says which. a config bundle exported from the gui names
no assets at all; `--bed-model`, `--bed-texture` and `--thumbnail` supply them.

## known conversion limits

all of these are reported per run. nothing is dropped silently.

- **sla presets are skipped** (`sla_print`, `sla_material`), as are
  `physical_printer` sections from config bundles
- **options that changed shape are dropped rather than guessed.**
  `avoid_crossing_perimeters_max_detour` was a percentage in 2.x and is plain
  millimetres in 3.x
- **filament-to-print-preset gating is lost.** 2.x could limit a filament to print
  presets whose `notes` matched a regex; 3.x has no `print.notes` condition
  variable, so such filaments become available on every print preset of the
  matching printer and nozzle
- host and serial settings (`octoprint_*`, `serial_port`, ...) have no place in a
  3.x vendor preset. 3.x keeps them on physical printers instead
- **custom g-code in orca's script dialect is translated, and read the note.**
  both slicers evaluate `{...}` blocks with locals and expressions, but orca also
  has `if cond then ... endif` and emits text by evaluating a string statement
  (`"G91\n";`) where prusaslicer wraps text in `{if}...{endif}` outside the
  braces, and 3.x refuses the whole template on either. `orca_script.py` turns
  one into the other. what it cannot carry across it says: an assignment to one
  of orca's own runtime variables (`position[2] = position[2] + 2.0`) is dropped,
  because 3.x has no such variable, and a template it cannot translate
  confidently is dropped whole rather than shipped half-done. a translated
  toolchange macro drives a tool head: read it before you print
- a round bed logs `Arrange.cpp:209 Bed segments are not supported for
  non-rectangular bed!` on every arrange. that is the app's own message for any
  non-rectangular bed, measured to be unaffected by whether the conversion
  declares `bed_segments_x/y` at all, and it does not stop anything

## verify

re-reads the 2.x source and the generated yaml and compares every custom-g-code
and text option (start and end g-code, per-layer g-code, filament g-code, notes,
ramming parameters, output filename format) after applying the same value
conversion. it catches the mistakes that matter most and show least: 2.x
serialises `start_filament_gcode` as a quoted vector item, so a naive read leaves
a stray `"` in the emitted g-code, and a yaml block scalar silently eats a
trailing newline unless the chomping indicator is chosen per value.

results on the bundles shipped with a 2.9.6 install:

| bundle | printers | values compared | mismatches |
|---|---|---|---|
| PrusaProHT | 2 | 559 | 0 |
| PrusaProAFS | 1 | 43 | 0 |
| Positron3D (prusawire) | 1 | 285 | 0 |
| Snapmaker (2.x) | 18, 10 of them dual-extruder | 595 | 0 |
| PrusaResearch | 37 | 24950 | 0 |
| Prusawire (vendor bundle) | 1 | 285 | 0 |
| Positron v3.2 (config bundle) | 1 | 20 | 0 |
| Snapmaker U1 (orca json) | 1, a 4-tool changer | 294 | 0 |

every conversion above also slices to g-code in 3.0.0-alpha10 after
`install --mode merge`, including two-material jobs on the dual-extruder
snapmakers and four-material jobs (pla, petg, abs, asa in one print with a wipe
tower) on the u1's 4-tool changer.

## orca and bambu json input

`convert` also reads an orcaslicer or bambustudio vendor index
(`resources/profiles/<Vendor>.json` plus the `<Vendor>/` tree beside it), which is
how a machine that never had a prusaslicer profile, the snapmaker u1 for one, can
be brought into 3.x. `orca.py` translates orca's names back to prusaslicer 2.x
ones and the normal pipeline does the rest. pass the `.json`; the reader is chosen
from the file's content.

**the mapping is derived, not guessed** (ADR-0002). orca ships profiles for the
same prusa machines prusaslicer 2.x ships, so each orca preset was aligned to its
2.x counterpart, by agreement on the ~115 option names both formats already share,
and the renames read off the pairs whose values agree. that is worth doing for the
cases intuition gets wrong: orca's `overhang_1_4_speed` is prusaslicer's
`overhang_speed_3`, not `_0`, because orca counts overhang in quarters of
supported extrusion width and prusaslicer in quarters of unsupported. 14 of 14
aligned pairs agree. the same derivation surfaced two keys misspelt in shipped
profiles (`detraction_speed`, `inital_layer_height`), which are honoured for
compatibility.

four fixes are what any orca conversion runs into, found by saving the resolved
config of a working printer and a failing one and borrowing values group by group
until it sliced:

- `filament_shrink` is inverted. orca states the printed size as a percentage of
  the intended one (100% is no shrinkage); prusaslicer states the compensation to
  apply (0% is none). passing 100 through scales the model by two
- custom g-code refers to options by name, so orca's names have to be rewritten
  inside the templates too. `[nozzle_temperature_initial_layer]` means nothing to
  prusaslicer
- orca escapes quotes inside expressions (`{if curr_bed_type==\"High Temp
  Plate\"}`) and 3.x rejects the escaped form
- a placeholder prusaslicer keeps per filament needs an index inside `{}`, where
  orca's scalar equivalent is written bare: `{first_layer_bed_temperature}` becomes
  `{first_layer_bed_temperature[0]}`

orca-only settings that its g-code branches on are inlined with the value the
profile states, so `{if curr_bed_type=="High Temp Plate"}` becomes a comparison
against the machine's actual `default_bed_type` and the branch decides what it
decided in orca. where the profile states no value, `--fix-gcode` neutralises the
reference with a literal matching what it is compared against.

orca-only options are otherwise dropped and reported: per-plate-type bed
temperatures (3.x has one bed temperature, so the plate named by the machine's
`default_bed_type` is the one carried), exhaust-fan and air-filtration settings,
nozzle hrc requirements, per-role jerk, ams drying, and so on.

orca also defaults some shared options differently, it addresses the extruder
relatively where prusaslicer does not, so a small table of verified orca defaults
is injected when a profile does not mention them. those are the ones whose
difference changes the slice; orca's defaults are not injected wholesale.

## tests

```bash
make test
```

300 tests, no network, no prusaslicer needed, and nothing that reads the machine
it runs on: the platform branches in `paths.py` are tested with `sys.platform` and
the environment monkeypatched, and everything else runs against a synthetic vendor
bundle. every bug this tool has had is one of them, named after the bug rather
than the function.
