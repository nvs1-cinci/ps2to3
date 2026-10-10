# changelog

notable changes to ps2to3. newest first.

## unreleased

### fixed
- orca: json files that start with a utf-8 byte-order mark are read instead of
  skipped. snapmaker ships `fdm_process_common.json` (the base of every print
  preset) and the u1's `0.20mm Standard` that way, so both silently went missing
- orca: `filament_shrinkage_compensation_z` is inverted like `filament_shrink`.
  orca's value is the printed size (100% = none) under the very name prusaslicer
  uses for a compensation, so it passed straight through as a 2x z scale and
  3.x refused every slice over `max_print_height`
- convert: a printer config's default tool is the standard 0.4 nozzle when the
  printer has one, not the smallest listed. the u1 opened on 0.2 mm tools

## 2026-08-31 (0.3.0)

### added
- tests: a suite over values, yaml emission, 2.x conditions, the orca reader and
  its script dialect, conversion shapes, install/restore, path discovery, the
  theme and the cli. every bug this tool has had is one of them
- paths: `ps2to3 paths` reports the data directories, 2.x bundles, schema and
  slicer this machine actually has, with where each was found
- cli: `restore`, for putting back what a prusaslicer preset update removed
- packaging: `pyproject.toml`, `Makefile` (`venv`, `test`, `lint`, `preflight`,
  `run`), and a `ps2to3` / `ps2to3-importer` entry point
- docs: `docs/decisions/` with the four decisions that shaped the tool
- packaging: `make dist` builds a reproducible `dist/ps2to3-<version>.zip` holding
  the app, the launchers and the documentation, and nothing else

### changed
- the single-module script is now the `ps2to3` package: `bundle`, `conditions`,
  `values`, `gcode`, `emit`, `hardware`, `convert`, `install`, `verify`, `orca`,
  `schema`, `paths`, `files`, and `gui/`. output is byte-identical to before
- data directories, 2.x bundles and prusaslicer itself are discovered from the
  platform's conventions and validated on disk, and nothing is hardcoded to one
  machine (ADR-0004)
- `PS2TO3_DATADIR` now wins over a discovered directory even before it exists
- converting and installing use the standard library only, so the click-to-run
  launchers work on a plain python. pyyaml is an extra, needed by `verify`
- reading a 3mf extracts its configuration to a temporary directory instead of
  writing beside the source file
- the importer window: minimum size derived from the form, a scrollbar when the
  content does not fit, a data-directory dropdown from discovery, and the
  installed 2.x bundles offered as sources
- the importer is styled like prusaslicer 3: its accent orange and greys, its ui
  font, flat surfaces with hairline rules instead of boxes, one orange button for
  the action that does the work, and a light or dark palette following the
  desktop's preference with a switch in the window. every colour is traceable to
  a prusaslicer resource in `gui/theme.py`
- the launchers run `python -m ps2to3.gui`, preferring `.venv` when there is one

### fixed
- orca: a template's own local variables are no longer rewritten. `--fix-gcode`
  turned `local`, `position` and the names a macro declares into `0`, so the
  snapmaker u1's toolchange macro became `0 0 = 350.0;`. 3.x refuses a template it
  cannot parse, and a refused toolchange template stops the slice the moment a
  tool change is needed: a multi-material u1 print failed with
  `(38, [toolchange_gcode])` and no g-code, while single-tool prints were fine
- orca: a template written in orca's script dialect (`if ... then`, string
  statements) is now dropped with a note instead of emitted for 3.x to refuse.
  prusaslicer emits its own tool change, so the u1 now slices four materials
  (1283 tool changes, three tools fed, 29.58 g to the wipe tower); the vendor's
  own preheat and pre-extrude lines are gone and have to be rewritten by hand
- install: refuses, before copying anything, when a conversion's printers set a
  feature the host vendor does not declare. an undeclared name is an unknown
  variable to the expression evaluator, and 3.0.0-alpha10 does not catch it -
  `EvalError: Unknown variable 'printer.supports_non_high_flow_nozzle'` took the
  whole app down
- verify: compares `gcode_substitutions` and `post_process` too. no prusa 3.x
  preset sets either, so a conversion is the only thing that can get their shape
  wrong, and nothing else here would have noticed
- orca: words inside a regex literal (`printer_notes=~/.*MARKER.*/`) are no longer
  read as option names, which reported a template as unexportable and, with
  `--fix-gcode`, rewrote the pattern
- orca: an index whose preset tree is missing is now an error. it used to fall back
  to the containing directory, which swept in every profile beside it - one u1
  conversion came out with fifteen printer models
- schema: `--schema` pointing at a file that is not there is an error, instead of
  silently converting against the shipped schema
- cli, importer: a source that does not exist reports which file and why, instead
  of a traceback
- file handles are closed. every one-shot read and write goes through `files`

### removed
- the browser-based importer (ADR-0003), the root-level `ps2to3.py`, `orca.py` and
  `importer.py` modules, and the 18 snapmaker models that are not the u1
