# contributing

## before a change

read `AGENTS.md`-free: this repo's conventions are the ones in the code around
you. two rules matter more than style:

- **the conversion path imports only the standard library.** the click-to-run
  launchers run on a plain python with no pip install. pyyaml is imported inside
  `verify`, which is the only thing that reads a conversion back
- **a conversion note is the output, not a log.** anything a conversion cannot
  carry across is counted and printed. adding a silent drop is a bug

## the loop

```bash
make venv          # .venv with the package and the dev extras
make preflight     # ruff and the test suite, everything that must pass
make run           # the importer window
```

every bug this tool has had is a test named after it. a fix ships with the test
that fails before it and passes after.

## the regression suite the tests cannot be

`make test` cannot prove a conversion still produces what prusaslicer accepts.
so: keep a known-good conversion of every source you have, re-run it after any
change to the conversion, and diff. only `vendor_indices.zip` may differ, and
only in its embedded timestamps.

then install it and slice something. a conversion that produces no printers is
usually the preset-id or the condition invariant, not the yaml.
