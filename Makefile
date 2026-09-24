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

airgap-verify: supply-tools  ## no network: verify signature, install, run (VERIFY_KEY=pub | CERT_IDENTITY=signer)
	COSIGN=$(abspath $(TOOLS)/cosign) SENTINEL_VERIFY_KEY=$(VERIFY_KEY) \
	SENTINEL_TRUSTED_ROOT=$(TRUSTED_ROOT) SENTINEL_TRUSTED_ROOT_SHA256=$(TRUSTED_ROOT_SHA256) \
	SENTINEL_CERT_IDENTITY=$(CERT_IDENTITY) \
	deploy/bundle/verify_offline.sh dist/sentinel-$$($(UV) run python -c 'import sentinel;print(sentinel.__version__)')-$(ARCH).tar.gz

tools:  ## fetch pinned nats-server, toxiproxy, uv into .tools/ (sha256-verified)
	$(UV) run python scripts/fetch_tools.py

demo-local: web tools  ## hub on :8000 and edge on :8001 over an emulated link (Ctrl-C to stop)
	$(UV) run python -m harness.demo

ddil:  ## run all four DDIL scenarios on a real two-node cluster, then write docs/ddil-results.md
	$(UV) run python -m harness.run all
	$(UV) run python -m harness.report

# ---- M4 supply chain (begin) ------------------------------------------------
# SBOMs, vulnerability scan + VEX, signing and offline verification. See
# docs/supply-chain.md. Every tool is pinned by sha256 in deploy/tools.lock.
.PHONY: supply-tools sbom scan vex bundles sign-local airgap-local airgap-selftest lint-release
HOST_ARCH := $(shell uname -m | sed 's/arm64/aarch64/;s/amd64/x86_64/')
TOOLS := .tools/$(HOST_ARCH)
# Verification policy for airgap-verify: exactly one of
#   VERIFY_KEY=<public key>            (local proof: `make sign-local`, or a site key)
#   CERT_IDENTITY=<signing workflow>   (keyless release; trusted root = the pinned one)
VERIFY_KEY ?=
CERT_IDENTITY ?=
TRUSTED_ROOT ?= $(if $(CERT_IDENTITY),$(abspath .tools/noarch/sigstore-trusted-root.json),)
TRUSTED_ROOT_SHA256 ?= $(if $(CERT_IDENTITY),$(shell awk '$$1 == "sigstore-trusted-root.json" {print $$4}' deploy/tools.lock),)

supply-tools:  ## fetch pinned cosign, syft, trivy, linters, Sigstore trust root (sha256-verified)
	$(UV) run python scripts/fetch_tools.py --arch $(HOST_ARCH) cosign cosign.sigstore.json syft trivy hadolint actionlint shellcheck sigstore-trusted-root.json

sbom: supply-tools  ## SPDX + CycloneDX SBOMs for the Python runtime and web console -> dist/sbom/
	$(UV) run python scripts/sbom.py

scan: supply-tools  ## Trivy scan of what ships; reviewed VEX checked and applied; any finding left fails -> dist/scan/
	$(UV) run python scripts/scan.py

vex: supply-tools  ## rescan, re-check evidence, rewrite deploy/vex/sentinel.openvex.json from statements.toml
	$(UV) run python scripts/scan.py --write-vex

bundles: web  ## build both air-gap bundles (x86_64 and aarch64)
	$(UV) run python scripts/build_bundle.py --arch x86_64 --arch aarch64

sign-local: supply-tools  ## LOCAL PROOF ONLY: sign dist bundles with an ephemeral key (destroyed after use)
	COSIGN=$(abspath $(TOOLS)/cosign) deploy/bundle/sign_local.sh --pubkey-out dist/local-signing-key.pub dist/sentinel-*.tar.gz

airgap-local: bundle sign-local  ## build, sign with an ephemeral key, then airgap-verify with that key
	$(MAKE) airgap-verify VERIFY_KEY=$(abspath dist/local-signing-key.pub)

airgap-selftest: supply-tools  ## real cosign, no network: tampering, wrong keys and wrong identities are rejected
	COSIGN=$(abspath $(TOOLS)/cosign) deploy/bundle/selftest_signature.sh

lint-release: supply-tools  ## actionlint (+shellcheck) on workflows, hadolint, shellcheck on deploy scripts
	$(TOOLS)/actionlint -shellcheck $(TOOLS)/shellcheck
	$(TOOLS)/hadolint deploy/containers/Dockerfile
	$(TOOLS)/shellcheck deploy/bundle/*.sh deploy/ansible/tests/*.sh
# ---- M4 supply chain (end) --------------------------------------------------
