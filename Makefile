# Sentinel - common tasks. `make help` lists them.
SHELL := /bin/bash
UV ?= uv
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: help install test lint web web-test serve dev report demo clean

help:  ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install:  ## python venv + web dependencies
	$(UV) venv -q --allow-existing && $(UV) pip install -q -e ".[dev]"
	npm --prefix web ci --no-audit --no-fund

test:  ## python test ladder (network disabled) + web tests
	$(UV) run pytest -q
	npm --prefix web test

lint:  ## ruff, module-boundary contracts, TypeScript
	$(UV) run ruff check .
	$(UV) run lint-imports
	npm --prefix web run typecheck

web:  ## build the operator console into web/dist
	npm --prefix web run build

serve: web  ## run a standalone node on :8000 with the exercise scenario
	$(UV) run sentinel serve --port 8000

dev:  ## API on :8000 + Vite dev server on :5173 (hot reload)
	( $(UV) run sentinel serve --port 8000 & ) ; npm --prefix web run dev

report:  ## regenerate docs/validation-report.md
	$(UV) run python scripts/validation_report.py

clean:
	rm -rf web/dist .pytest_cache .ruff_cache dist build
