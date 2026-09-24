# Sentinel - common tasks. `make help` lists them.
SHELL := /bin/bash
UV ?= uv
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: help install test lint web web-test serve dev report ai-eval demo clean bundle airgap-verify tools demo-local ddil

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

ai-eval:  ## score the assistant's routers on evals/routing.jsonl -> docs/ai-eval.md (Jev only if TYPESAFE_API_KEY is set)
	$(UV) run python scripts/ai_eval.py

clean:
	rm -rf web/dist .pytest_cache .ruff_cache dist build

ARCH ?= x86_64
bundle: web  ## build dist/sentinel-<ver>-$(ARCH).tar.gz (ARCH=x86_64|aarch64)
	$(UV) run python scripts/build_bundle.py --arch $(ARCH)

airgap-verify:  ## install the x86_64 bundle and run it with networking disabled
	deploy/bundle/verify_offline.sh dist/sentinel-$$($(UV) run python -c 'import sentinel;print(sentinel.__version__)')-x86_64.tar.gz

tools:  ## fetch pinned nats-server, toxiproxy, uv into .tools/ (sha256-verified)
	$(UV) run python scripts/fetch_tools.py

demo-local: web tools  ## hub on :8000 and edge on :8001 over an emulated link (Ctrl-C to stop)
	$(UV) run python -m harness.demo

ddil:  ## run all four DDIL scenarios on a real two-node cluster, then write docs/ddil-results.md
	$(UV) run python -m harness.run all
	$(UV) run python -m harness.report

# --- M6 MBSE: requirement trace and SysML v2 syntax check (begin) -----------
# sysml2py carries the SysML v2 pilot implementation's grammar (ported to
# textX). It pins astropy<6, which has no Python 3.13 wheels, so it runs in an
# isolated environment rather than in the project's dev extra.
SYSML2PY ?= sysml2py==0.5.3
.PHONY: trace sysml-check

trace:  ## regenerate docs/traceability.md from mbse/*.sysml (fails on a broken reference)
	$(UV) run python scripts/trace.py

sysml-check:  ## parse mbse/*.sysml with the SysML v2 pilot grammar (sysml2py, isolated env)
	$(UV) run --no-project --isolated --python 3.12 --with '$(SYSML2PY)' --with 'setuptools<81' \
		python scripts/sysml_check.py mbse/*.sysml
# --- M6 MBSE (end) -----------------------------------------------------------
