#!/bin/sh
# linux: double-click, or run ./ps2to3-importer.sh
# runs from the checkout, so no install step is needed.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python -m ps2to3.gui "$@"
fi
PYTHONPATH=src exec python3 -m ps2to3.gui "$@"
