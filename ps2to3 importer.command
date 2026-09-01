#!/bin/sh
# macos: double-click this in finder. chmod +x once, if finder refuses.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python -m ps2to3.gui "$@"
fi
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then
    PYTHONPATH=src exec "$py" -m ps2to3.gui "$@"
  fi
done
osascript -e 'display alert "ps2to3 importer" message "Python 3 is not installed. Install it from python.org, then double-click again."' 2>/dev/null
exit 1
