# ADR-0003: a tkinter window, not a browser ui

- status: accepted
- date: 2026-08-31
- deciders: repo owner

## context

the importer needs a ui: a conversion takes a profile source plus the artwork a
printer needs (bed model, bed texture, thumbnail), and the requirement was
click-to-run on linux, macos and windows, with no browser, and the whole app stack
gone when the window closes.

the first implementation was a local http server plus the system browser. it
worked and was wrong for the requirement: it needed a browser, the server outlived
the tab, and it broke on python 3.13, which removed `cgi` (the multipart parsing
had to be rewritten on `email`).

## decisions

chosen: tkinter, in-process, with the window owning the lifetime.

- a browser ui was rejected: it fails the no-browser and close-the-stack
  requirements outright
- pyside/wx were rejected: they need a wheel per platform, which fails
  click-to-run on a machine with a plain python
- tkinter ships with cpython on all three platforms, so a launcher script is the
  whole install

consequences of that choice, decided with it:

- closing the window calls `destroy()` then `os._exit(0)`, because a converter
  thread must not keep the process alive after the window is gone
- the form lives in a scrollable canvas with a minimum window size derived from
  the form itself, clamped to the screen
- the conversion path imports nothing outside the standard library, so the
  launchers work without a pip install. pyyaml is needed only by `verify`

## consequences

- one file to double-click on every platform, and no browser
- the window is themed to look like prusaslicer 3 rather than like tk: the
  palette is read off the slicer's own resources (`gui/theme.py` names the file
  each colour comes from), which means clam is the theme in use, since it is the
  only built-in one that takes colours from a style. tkinter still has no rich
  widgets, so anything beyond flat surfaces, hairline rules and one accent button
  is not available
- the ui and the cli share one code path (`Conversion`), so a fix reaches both
- a headless machine gets the cli, which is the full feature set anyway
