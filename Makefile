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

# >>> compliance (M4) >>>
# OSCAL package (compliance/, docs/compliance.md): test evidence in, assessment
# results and POA&M out, then trestle validates the whole workspace. A failing
# test still produces its POA&M item; the target fails afterwards.
TRESTLE ?= uvx --from compliance-trestle==5.1.0 trestle
COMPLIANCE_BUILD ?= build/compliance
XCCDF ?=
.PHONY: compliance compliance-catalog

compliance: compliance-catalog  ## OSCAL package: pytest evidence -> assessment results + POA&M, trestle validate -a (XCCDF=scan results)
	mkdir -p $(COMPLIANCE_BUILD)
	$(UV) run pytest -q --junitxml=$(COMPLIANCE_BUILD)/junit.xml; echo $$? > $(COMPLIANCE_BUILD)/pytest.status
	$(UV) run python scripts/oscal_evidence.py --junit $(COMPLIANCE_BUILD)/junit.xml \
		$(if $(wildcard harness/results/*.json),--harness harness/results) $(if $(XCCDF),--xccdf $(XCCDF))
	cd compliance/oscal && $(TRESTLE) validate -a
	@test "$$(cat $(COMPLIANCE_BUILD)/pytest.status)" = 0 || { echo "pytest failed: the failures are in the POA&M"; exit 1; }

compliance-catalog:  ## verify the vendored NIST SP 800-53 Rev 5 catalog, then import it into the trestle workspace
	cd compliance/vendor/nist && sha256sum --strict -c SHA256SUMS
	rm -rf compliance/oscal/catalogs/nist-800-53-rev5
	cd compliance/oscal && $(TRESTLE) import -f ../vendor/nist/NIST_SP-800-53_rev5_catalog-min.json -o nist-800-53-rev5
# <<< compliance (M4) <<<
