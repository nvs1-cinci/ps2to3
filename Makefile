# ps2to3 - convert printer profiles into the prusaslicer 3.x preset format
#
# every target runs out of the local .venv, so nothing here touches the system
# python (this distribution's is externally managed).

PY      := .venv/bin/python
PIP     := .venv/bin/pip
RUFF    := .venv/bin/ruff
PS2TO3  := .venv/bin/ps2to3

.DEFAULT_GOAL := help
.PHONY: help venv test lint fmt run cli preflight dist clean

# ── setup ───────────────────────────────────────────────────────────────────

venv: .venv/bin/python  ## create the venv and install the package for development
.venv/bin/python:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e '.[dev]'

# ── checks ──────────────────────────────────────────────────────────────────

test: venv  ## run the test suite
	$(PY) -m pytest

lint: venv  ## static checks
	$(RUFF) check .

fmt: venv  ## apply the fixes ruff can make on its own
	$(RUFF) check --fix .

preflight: lint test  ## everything that must pass before a commit
	@echo "preflight ok"

# ── running ─────────────────────────────────────────────────────────────────

run: venv  ## open the importer window
	$(PY) -m ps2to3.gui

cli: venv  ## show what this machine looks like to the tool
	$(PS2TO3) paths

# ── distribution ────────────────────────────────────────────────────────────

dist: preflight  ## build the zip to hand to somebody else (dist/ps2to3-<version>.zip)
	$(PY) scripts/make_dist.py

# ── housekeeping ────────────────────────────────────────────────────────────

clean:  ## remove build and cache directories
	rm -rf build dist .pytest_cache .ruff_cache src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

help:  ## list the targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
	  | sed 's/:.*## /\t/' | expand -t22
