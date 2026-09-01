# ADR-0004: discover prusaslicer's paths by validating them

- status: accepted
- date: 2026-08-31
- deciders: repo owner

## context

the tool has to find three things on a machine it has never seen: prusaslicer 3's
data directory (where a conversion is installed), the 2.x bundles already
installed (the most likely conversion source), and prusaslicer itself (to export
the option schema).

early versions had the developer's own paths in them. that works on one machine
and silently installs into nowhere on every other.

the platforms disagree, and so do the packaging formats. flatpak redirects
`~/.config` into `~/.var/app/<id>/config`, snap into
`~/snap/prusaslicer/current/.config`, and the alpha's directory name
(`PrusaSlicer3-dev`) is not the name the release will use.

## decisions

chosen: enumerate candidates from the platform's own conventions plus the
environment, then report a candidate only with what is actually on disk behind it.
`presets/local/prusa-research-fff/PrusaResearch/vendor.yaml` is the file that
proves a directory is a prusaslicer 3 data directory, so it is what gets checked.

- a single hardcoded path per platform was rejected: it cannot tell a flatpak
  install from a native one
- asking the user first was rejected as the default: the answer is derivable, and
  a wrong default is what the validation is for. `PS2TO3_DATADIR` and
  `PS2TO3_SLICER` stay available for the machine where it is not
- an explicit override is **not** ranked against the discovered candidates. it
  goes first even when it does not exist yet, because quietly preferring a
  better-looking directory is how a conversion lands somewhere nobody looks

candidates carry their origin (`APPDATA`, `flatpak`, `~/.config`) and their state
(`ready`, `no PrusaResearch vendor yet`, `empty`, `not present`), and both the cli
(`ps2to3 paths`) and the importer's dropdown show them.

## consequences

- nothing in the tool names a person's home directory
- `ps2to3 paths` is the first thing to run on a machine where something is off,
  and its output is the whole diagnosis
- a new packaging format (a future snap path, a new alpha directory name) is one
  entry in `DATA_DIR_NAMES` or `_config_roots()`
- the platform branches are tested with the platform and environment
  monkeypatched, so a linux machine still covers the windows and macos layouts
