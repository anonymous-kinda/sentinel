# 12. Supply chain and deployment

## What you will learn

- How every third-party binary Sentinel runs is pinned by sha256, fetched by one function, and re-hashed each time it is reused.
- What an air-gap bundle contains, why two builds of one commit give the same bytes, and how `install.sh` refuses anything the signed list does not name.
- How keyless signing works, why it verifies on a host with no network, and what "SLSA Build L2" does and does not promise.
- How SBOMs, a Trivy gate and VEX statements fit together, and why a VEX statement must answer a finding a real scan produced.
- Which deployment targets exist (systemd, Ansible with a STIG role, Terraform, containers, Compose) and which of them have never run.

## Why it exists

A disconnected site cannot `pip install` anything. It cannot reach Sigstore, GitHub or a package index. Its approver, usually an ISSM, still has to answer three questions before the software goes near the network:

1. **Is this what the developer built?** A signature that verifies on the enclave host, against a trust anchor the site already holds.
2. **What is in it?** A component inventory (SBOM) and a per-file manifest.
3. **What is known to be wrong with it?** A vulnerability scan, and a reviewed, checkable reason for every finding that is not fixed.

Sentinel answers all three with files that travel beside the bundle. The same bundle installs the AWS hub, an edge laptop and an enclave node. In DoD work, getting approval to operate often takes longer than building the software, and this chapter's code produces much of the evidence that approval needs. [ADR-012](../system-design.md#adr-012--keyless-signing-verified-offline-against-a-pinned-trust-root) records the decision, and [docs/supply-chain.md](../supply-chain.md) lists every release asset and the control each one serves.

The rule is the one Sentinel applies to CDM ingest. An input that would make the answer wrong is refused, not warned about. An unsigned bundle is never unpacked. A VEX statement that answers no real finding fails the build. An SBOM that misses a shipped component fails the build.

## Concepts

### Pinning by digest

A version number names a release, but the file behind a URL can change. A sha256 digest names the exact bytes. `deploy/tools.lock` pins every third-party binary by version, architecture, download URL and sha256. Each digest was computed locally from the downloaded file and cross-checked against the digest the project publishes. From then on, a download that hashes to anything else is refused.

Python dependencies get the same treatment through `uv.lock`, which records a sha256 for every wheel. `uv export` turns the lock into a `requirements.txt` with `--hash=` lines, and `pip` or `uv pip` with `--require-hashes` refuses any wheel whose hash is not listed.

### Reproducible builds

If two builds of one commit give different bytes, a digest proves nothing about the source. The bundle builder removes every source of variation it controls: entries in sorted order, owner `root`, normalised modes, and every timestamp set to `SOURCE_DATE_EPOCH`, which defaults to the commit time. That includes the gzip header and the zip entries inside the sentinel wheel. Across two machines with different zlib or Python builds, reproducibility has not been shown.

### Signing without a long-lived key

Classic signing uses a private key that someone has to guard, rotate and eventually revoke. Sigstore's *keyless* signing replaces the key with an identity:

```
release.yml, sign job (the only job with id-token: write)
  GitHub OIDC token ──> Fulcio (certificate authority)
                        issues a certificate valid for minutes, naming
                        https://github.com/OWNER/sentinel/.github/workflows/release.yml@refs/tags/vX.Y.Z
  cosign sign-blob ───> Rekor (public transparency log): an inclusion proof
                   └──> TSA: an RFC 3161 timestamp
  result: <artifact>.sigstore.json = signature + certificate + log proof + timestamp

enclave host, no network
  cosign verify-blob --bundle <artifact>.sigstore.json
         --trusted-root trusted_root.json       Fulcio CA, Rekor, CT log and TSA keys
         --certificate-identity <that exact workflow at that tag>
         --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Everything cosign needs is in two files: the Sigstore bundle beside the artifact, and `trusted_root.json`. The trust root is pinned by sha256 in `deploy/tools.lock`. So the check needs no network: cosign verifies the certificate chain, the log's inclusion proof and the timestamp against keys it already holds. The identity check matters as much as the signature. Anyone can get a Fulcio certificate for *their own* workflow, so the policy must name this repository's `release.yml` at this tag, exactly.

*Key mode* still exists, for two cases. A site may countersign approved software with its own key, and a developer's machine has no GitHub OIDC token, so local proofs sign with a throwaway key. A key signature has no transparency-log entry, so the verifier skips that check and says so.

### SLSA build levels

SLSA grades how much you can trust a statement about *how* an artifact was built (its provenance).

```
L1  provenance exists and describes the build
L2  a hosted platform builds, and signs the provenance     <-- Sentinel claims this
L3  the provenance cannot be forged by the build's own steps; builds are isolated
```

Sentinel's provenance is produced by `actions/attest-build-provenance` inside the repository's own workflow. Anyone who can change `release.yml` could have the platform sign provenance for something it did not build. That is why the claim stops at L2. Reaching L3 means moving the build into an isolated, trusted reusable workflow.

### SBOMs, scans and VEX

An **SBOM** (software bill of materials) lists the components that ship. Sentinel writes each one in two formats, SPDX and CycloneDX, with syft. A **scanner** (Trivy) matches components against vulnerability databases. It reports by package, not by code path, so it can flag a module whose vulnerable function is never linked. A **VEX** statement (Vulnerability Exploitability eXchange) is the product owner's answer to one finding: `not_affected`, `affected`, `fixed` or `under_investigation`. For `not_affected`, it adds a justification from a fixed vocabulary and a written reason.

VEX is a suppression mechanism, which makes it dangerous. Sentinel constrains it three ways. A statement must answer a finding a raw scan reported. Its reason must be written down. Where the reason can be checked mechanically, the check reruns on every scan against the binaries that ship.

### Fail closed

Every gate in this chapter has three outcomes: pass, refuse with a named reason, or crash. The code keeps "refuse" and "crash" apart. The vulnerability gate exits 5 for "findings remain", distinct from Trivy's own error exit of 1, so a crashed scan can never be read as a result.

## Code walkthrough

### 1. Pins: `deploy/tools.lock`, `supplychain/toolslock.py`, `scripts/fetch_tools.py`

`deploy/tools.lock` is a whitespace table: `name version arch sha256 url member`. `arch` is `x86_64`, `aarch64` or `noarch` (the Sigstore trust root). `member` is the path inside a `.tar.gz`, or `-` for a file served as-is.

In `supplychain/toolslock.py`:

- `parse` rejects a row with the wrong column count or a digest that is not 64 lowercase hex characters. A malformed lock is an error before anything downloads.
- `select` returns the rows for one architecture plus the `noarch` rows. It raises `LockError` when a requested name has no pin, so asking for a tool the lock does not cover is never a silent partial fetch.
- `fetch` does the work. It downloads, hashes the whole download, compares it with the pin, extracts the member if there is one, writes the file (mode 644 for JSON trust material, 755 otherwise), and writes a stamp file `.<name>.sha256` beside it. On a mismatch it logs `Pinned download digest mismatch` with the tool, the architecture and both digests as fields, raises, and writes nothing.

**The part that is easy to get wrong** is reuse. `fetch` skips the download when the file is already there, but only if the stamp equals `_stamp(pin, current bytes)`. The stamp holds two digests: the pin that was verified, and the digest of the file *as written*. The second is needed because a file extracted from an archive has no pin of its own. So every reuse re-hashes the file on disk. An earlier version trusted the stamp alone, so a binary swapped after download was reused and shipped in a bundle whose manifest still quoted the pinned digest. `tests/supplychain/test_toolslock.py::test_a_reused_tool_is_the_verified_one_not_whatever_is_on_disk` is the regression test.

`scripts/fetch_tools.py` is a thin CLI over `select` and `fetch`: `--arch` (default: this host) and optional names. Files land in `.tools/<arch>/`, and trust material in `.tools/noarch/`. `make tools` fetches the two binaries the harness runs. `make supply-tools` fetches cosign, syft, trivy, the linters and the trust root.

### 2. The bundle: `scripts/build_bundle.py`, `supplychain/bundle.py`, `supplychain/checksums.py`

`build` in `scripts/build_bundle.py` runs seven numbered steps:

```
sentinel-<ver>-<arch>/
  wheels/            1. the sentinel wheel;  3. every dependency, cp312 manylinux, hash-checked
  requirements.txt   2. export_requirements(): uv export --frozen --no-dev, with --hash lines
  bin/               4. uv and nats-server for the target arch, through fetch()
  web/ fixtures/     5. the built console; NASA CARA data and the element-set snapshot
  systemd/ install.sh LICENSE VERSION
  BUNDLE.json        6. bundle_manifest(): commit, clean|dirty, epoch, tools, wheel digests
  SHA256SUMS         6. write_manifest(): every file, written last
-> sentinel-<ver>-<arch>.tar.gz (+ .sha256)   7. write_tarball()
```

- `export_requirements` is the one definition of the runtime dependency set: no dev tools and no optional AI extras. The bundle, the container and the Python SBOM all install exactly this.
- `stage_fixtures` copies `SHIPPED_FIXTURES` (`cara`, `cara_cases.json`, `omm`) unmodified, with their provenance files. If one is missing from the source, the build fails.
- `bundle_manifest` records the pinned binaries with their upstream URL and digest, and the digest of every wheel. It also records `source_tree: dirty` when `git status` shows uncommitted changes, so a bundle built from an edited tree cannot pass as its commit.
- `write_tarball` normalises every entry (`normalise`: uid and gid 0, owner `root`, mtime = epoch, mode 755 or 644) and writes the gzip header with the same epoch and no file name.
- `manifest_text` in `supplychain/checksums.py` produces lines byte-compatible with `sha256sum --strict -c`, sorted by relative path, and never lists `SHA256SUMS` itself.

**Easy to get wrong:** `SHA256SUMS` must be the last file written. Anything written after it, including `BUNDLE.json`, would be outside the list. Note also that `build` exports `SOURCE_DATE_EPOCH` into its own environment before `uv build`, because the wheel's zip timestamps come from it.

### 3. The gate: `deploy/bundle/verify_signature.sh`

One script decides whether a signature is acceptable, for `make airgap-verify`, `deploy/bundle/verify_offline.sh`, the release workflow and the Ansible role alike. In order, it:

1. refuses when the artifact or `<artifact>.sigstore.json` is missing ("an unsigned artifact is never installed");
2. picks exactly one policy: key mode (`SENTINEL_VERIFY_KEY`) or keyless mode (`SENTINEL_TRUSTED_ROOT` plus `SENTINEL_CERT_IDENTITY`). Both at once is "ambiguous policy", and neither is "no verification policy";
3. in keyless mode, compares the trust root's sha256 with `SENTINEL_TRUSTED_ROOT_SHA256` when that is set;
4. runs `cosign verify-blob` with the policy's flags. Key mode adds `--insecure-ignore-tlog` and prints that the transparency log was skipped.

Every refusal in steps 1 to 3 happens before cosign runs. `tests/supplychain/test_verify_signature.py` pins this with a stub cosign that records its argv. That makes it possible to assert, for example, that keyless mode never passes `--insecure-ignore-tlog`.

### 4. The installer: `deploy/bundle/install.sh`

`install.sh` runs after the signature has been verified and the tarball unpacked. It does not verify the signature itself. It:

1. runs `sha256sum --quiet --strict -c SHA256SUMS`;
2. refuses any file under `web`, `fixtures`, `bin`, `wheels` or `systemd` that the list does not name, using `comm` on sorted lists;
3. requires `python3.12` on the host, and sets `UV_OFFLINE=1`, `UV_NO_CACHE=1` and `UV_PYTHON_DOWNLOADS=never`;
4. installs dependencies with the bundled `uv`, using `--no-index --find-links wheels --require-hashes`, then the sentinel wheel with `--no-deps`;
5. copies the console, fixtures and binaries under `PREFIX` (default `/opt/sentinel`), and writes `sentinel.env` only if none exists;
6. with `SYSTEMD=1`, creates the `sentinel` system user, renders the unit with `@PREFIX@` substituted, and starts it.

**Easy to get wrong:** `sha256sum -c` checks only the files the list names. The installer copies whole directories and globs `wheels/sentinel-*.whl`, so a file added after signing would have ridden along unverified. Step 2 closes that hole. It uses `! -type d`, so an added symlink is refused too. `tests/supplychain/test_install_integrity.py` runs the real installer against a miniature bundle with a stub `uv` to prove it.

### 5. The local proofs: `verify_offline.sh`, `sign_local.sh`, `selftest_signature.sh`

- `deploy/bundle/verify_offline.sh` runs the whole install inside `unshare -rn`, a namespace with only loopback. It first proves the namespace has no network. Then it verifies the signature, checks the `.sha256`, unpacks, installs as a hub, and starts the node on port 18799 with an in-memory database. The node must reproduce the NASA validation, load element sets for every catalogued imager, and serve the console and the offline globe imagery.
- `deploy/bundle/sign_local.sh` is the offline stand-in for CI signing. It makes a key pair in a mode-700 temporary directory, encrypted with a random password that is never stored, and signs with a signing config that lists no Fulcio, Rekor or TSA. It deletes the private key on exit.
- `deploy/bundle/selftest_signature.sh` (`make airgap-selftest`) runs the real, pinned cosign inside `unshare -rn`. In key mode, a good signature must pass, and a tampered artifact, another key, a missing signature and a missing policy must fail. In keyless mode it verifies cosign's own release binary, signed by the Sigstore project, against the pinned trust root, and refuses a wrong identity and a trust root that does not match its pin.

**Easy to get wrong:** a refusal must be refused *for the right reason*. `expect` in the self-test checks the exit code and also looks for a specific message in stderr. A verifier that fails for an unrelated reason, or a fake cosign that always exits 0, shows up as `WRONG`.

### 6. SBOMs: `scripts/sbom.py`, `supplychain/sbom.py`

`stage_python` installs the exported requirements and the sentinel wheel into a staging directory for CPython 3.12 manylinux (`uv pip install --target ... --python-platform ... --require-hashes`). syft then catalogues the *installed* metadata, so environment markers resolve as they do in the bundle. `stage_web` copies only `web/package.json` and `web/package-lock.json`; syft leaves out devDependencies. `syft_command` asks for both formats in one pass.

`require_components` is the gate. An SBOM with no components fails, and so does one missing a component known to ship (the `SUBJECTS` sets). **Easy to get wrong:** syft lists each installed file as a CycloneDX component of type `file`. `component_names` drops those, or an SBOM of nothing but files would look complete.

### 7. Scan and VEX: `scripts/scan.py`, `supplychain/trivy.py`, `supplychain/vex.py`, `supplychain/evidence.py`

`scripts/scan.py` has three stages:

```
1. raw scans, JSON, nothing suppressed
     trivy fs .                  uv.lock and web/package-lock.json
     trivy rootfs <staged bin>   uv and nats-server, both arches, fetched through fetch()
2. vex.build(...)                each statement answers a raw finding; its evidence holds;
                                 the committed document equals the generated one (--check)
3. gate, SARIF, --vex applied, --exit-code 5
     exit 5 -> "Unaddressed vulnerabilities" -> exit 1;  any other non-zero -> "Trivy scan failed"
```

`trivy_command` in `supplychain/trivy.py` is the one place the argv is built, with telemetry and version checks off. `findings` reads a Trivy JSON report into `Finding(vulnerability, purl, target, severity)`.

In `supplychain/vex.py`:

- `load` parses `deploy/vex/statements.toml`. It refuses unknown keys (a typo is an error, not an omission). `not_affected` needs a justification from `JUSTIFICATIONS` and an `impact_statement`, and `affected` needs an `action_statement`.
- `stale` returns statements whose `(vulnerability, purl)` matches no finding, checking the subcomponents and the products. `build` raises on any.
- `verify_evidence` runs each statement's evidence check against every binary it names, under `.tools/`.
- `document` and `validate_document` produce OpenVEX 0.2.0. The schema requires at least one statement, so with none, `build` deletes the document instead of writing an empty one.

`GoPackageAbsent.verify` in `supplychain/evidence.py` backs the one current statement. A Go binary keeps its function names even when stripped, so a linked package leaves its import path in the file. The check requires the vulnerable package's path to be absent **and** a control package's path to be present. **Easy to get wrong:** without the control, an absence check passes on a binary that is compressed, the wrong file, or not a Go binary at all. Absence you cannot see proves nothing.

`make vex` runs the scan with `--write-vex` and rewrites `deploy/vex/sentinel.openvex.json`. That file is generated; never edit it by hand.

### 8. The workflows: `.github/workflows/` and `tests/test_workflows_pinned.py`

- `.github/workflows/ci.yml` runs on every push to main and every pull request. Its jobs: `python` (a 3.11, 3.12 and 3.13 matrix: ruff, import contracts, mypy, the test ladder, and checks that the validation report, AI eval and ICDs regenerate unchanged), `web`, `infra` (Terraform fmt and validate, Ansible syntax), `secrets` (gitleaks), `mbse`, `release-lint`, `supply-chain` (SBOMs, the vulnerability gate, the signature self-test, the Ansible signature gate), `compliance`, `compose-smoke` and `airgap-install`. The last one runs `make airgap-local` once on `ubuntu-24.04` for x86_64 and once on `ubuntu-24.04-arm` for aarch64, with no dependency cache.
- `.github/workflows/harness.yml` runs the six DDIL scenarios on real processes. It triggers on pull requests that touch the link layers, runs nightly with a 15-minute denial, and can be started by hand.
- `.github/workflows/release.yml` runs on a `v*` tag. `build` checks that the tag equals `sentinel.__version__`, builds both bundles, the SBOMs and the gate. `container` builds and smoke-tests an image per architecture from the unpacked bundle. `sign`, the only job with `id-token: write`, runs no build code: it assembles `SHA256SUMS`, signs keyless, verifies every signature offline inside `unshare -rn` against the pinned root and the exact identity, then attests provenance and SBOMs. `verify` installs each bundle offline on its own architecture. `code-scanning` uploads the SARIF results, pass or fail. `publish` creates a **draft** release for a maintainer to publish.

The whole of `release.yml` has `permissions: {}` at the top, and each job is granted only what it needs.

`tests/test_workflows_pinned.py` holds four rules, and each has a test proving the check catches a violation:

- `unpinned`: every `uses:` outside `./` ends in a 40-hex commit SHA. A tag like `@v4` can be moved to other code after review.
- `unlocked_installs`: no `pip install` or `uv pip install` line, because those resolve afresh.
- `unlocked_uv_jobs`: every job that sets up uv has `UV_LOCKED=1` (for the workflow or the job) or runs `uv sync --locked`.
- `unpinned_tools`: every `uvx --from PKG` in the workflows and the Makefile carries `==`.

**Easy to get wrong:** `uv sync --locked` in the install step is not enough. A later `uv run` re-locks silently if `uv.lock` is stale, so a job could test dependencies nobody reviewed. `UV_LOCKED: "1"` makes that an error in every uv command.

### 9. Where it lands: the deployment targets

| Target | Files | What it does | Checked by |
|---|---|---|---|
| systemd | `deploy/systemd/sentinel.service` | Runs as user `sentinel` on 127.0.0.1:8000; `ProtectSystem=strict` with only `<prefix>/var` writable; no capabilities; `@system-service` syscall filter; default log level `warning`, which `sentinel.env` can override | `tests/test_deploy_env.py`, `tests/compliance/test_deploy_conformance.py` |
| Ansible | `deploy/ansible/site.yml`, roles `baseline`, `sentinel`, `caddy`, `stig` | Installs the same signed bundle on a hub, with Caddy for TLS in front. `roles/sentinel/tasks/verify.yml` runs the signature gate on the target before anything is unpacked | `deploy/ansible/tests/test_verify.sh` (CI `supply-chain`), syntax check (CI `infra`) |
| STIG role | `deploy/ansible/roles/stig/` | A documented subset of the DISA Ubuntu 24.04 STIG; checks the settings in effect (`sshd -T`), not the files written; optional OpenSCAP scan converted to a `.ckl` checklist | `tests/compliance/test_stig_role.py`, chapter 13 |
| AWS | `deploy/aws/terraform/` | One Graviton instance in its own VPC: IMDSv2 only, encrypted root, SSH only from `admin_cidr` (which may never be `0.0.0.0/0`), Session Manager for break-glass access, leaf port closed unless allow-listed, a budget alarm | CI `infra` (fmt, validate) |
| Release image | `deploy/containers/Dockerfile` | Built from an unpacked, verified bundle; re-checks `SHA256SUMS`; Chainguard base pinned by digest; non-root, read-only root | release `container` job |
| Compose | `deploy/compose/compose.yaml`, `deploy/compose/Dockerfile` | Hub and edge, each with its own nats-server, over one Toxiproxy link; the image builds from source | `tests/test_compose_stack.py`, `tests/test_compose_config.py`, `tests/test_compose_image.py`, `tests/test_compose_wiring.py`, `tests/test_compose_smoke.py`; CI `compose-smoke` |

In `deploy/ansible/roles/sentinel/tasks/verify.yml`, **the part that is easy to get wrong** is the verifier itself. The play copies the pinned cosign to the host and checks its sha256 *on the host* against the digest it pulls out of `deploy/tools.lock` (`sentinel_cosign_sha256` in the role's defaults). A cosign swapped on the controller or in transit would otherwise be trusted to judge the bundle.

## Try it

Every command in this section was run while this chapter was written, with no network beyond what was already cached: the pinned binaries in `.tools/` and uv's package cache. Commands that need a network the first time are listed at the end.

**Pinned tools, and a reuse that needs no network.** The first `make tools` downloads. The second, inside a namespace with no network, must reuse both files without touching the network:

```bash
make tools
unshare -rn make tools
```

Look for one line per tool, with the version from `deploy/tools.lock` and the path under `.tools/`.

**A swapped binary is not reused.** Back up a tool, append one byte, and ask for it with no network:

```bash
mkdir -p build && cp .tools/x86_64/toxiproxy build/toxiproxy.bak
printf 'x' >> .tools/x86_64/toxiproxy
unshare -rn uv run python scripts/fetch_tools.py toxiproxy    # tries to download again
cp build/toxiproxy.bak .tools/x86_64/toxiproxy
unshare -rn make tools                                        # quiet reuse again
```

The third command ends in a `URLError` traceback ("Temporary failure in name resolution"). That is the proof: `fetch` noticed the file no longer matched its stamp and went to download a fresh copy. With a network, it would have replaced the file.

**The supply-chain unit tests, with no network at all:**

```bash
unshare -rn uv run pytest -q tests/supplychain tests/test_workflows_pinned.py
```

Everything passes. The verifier's policy tests (`tests/supplychain/test_verify_signature.py`) are the offline signature self-test: a stub cosign records its argv, so each refusal is shown to happen before cosign runs.

**The verifier's refusals, without cosign:**

```bash
mkdir -p build/try && echo demo > build/try/b.tar.gz
deploy/bundle/verify_signature.sh build/try/b.tar.gz
echo '{}' > build/try/b.tar.gz.sigstore.json
deploy/bundle/verify_signature.sh build/try/b.tar.gz
SENTINEL_VERIFY_KEY=build/try/site.pub SENTINEL_CERT_IDENTITY=me deploy/bundle/verify_signature.sh build/try/b.tar.gz
echo '{}' > build/try/root.json
SENTINEL_TRUSTED_ROOT=build/try/root.json SENTINEL_CERT_IDENTITY=me \
SENTINEL_TRUSTED_ROOT_SHA256=$(awk '$1 == "sigstore-trusted-root.json" {print $4}' deploy/tools.lock) \
  deploy/bundle/verify_signature.sh build/try/b.tar.gz
```

Each exits 1, in turn with `no signature bundle`, `no verification policy`, `ambiguous policy` and `trusted root digest ... does not match the pinned ...`.

**The installer refuses what its list does not name.** Build a two-file "bundle", list it, then add a file:

```bash
mkdir -p build/try/mini/web && echo '<!doctype html>' > build/try/mini/web/index.html
cp deploy/bundle/install.sh build/try/mini/
uv run python -c 'import pathlib; from supplychain.checksums import write_manifest; write_manifest(pathlib.Path("build/try/mini"))'
cat build/try/mini/SHA256SUMS
echo 'added after signing' > build/try/mini/web/injected.js
PREFIX=/nonexistent SYSTEMD=0 build/try/mini/install.sh
```

Look for `install: refusing files that SHA256SUMS does not list:`, followed by the added file's path relative to the bundle. Now remove the added file and change a listed one instead (`rm build/try/mini/web/injected.js; echo changed >> build/try/mini/web/index.html`). Run the installer again, and `sha256sum` reports the changed file as `FAILED`. Both refusals happen before anything is written under `PREFIX`.

**The dependency set every artifact installs:**

```bash
uv export --frozen --no-dev --no-emit-project --format requirements-txt > build/try/requirements.txt
head build/try/requirements.txt
```

Each package is pinned with `==` and one or more `--hash=sha256:` lines. `--frozen` reads `uv.lock` without re-resolving, so this works offline.

**The VEX rule: a statement must answer a real finding.** Give the VEX builder a scan that found nothing:

```bash
echo '{"SchemaVersion": 2, "Results": []}' > build/try/clean-scan.json
uv run python -m supplychain.vex --statements deploy/vex/statements.toml \
  --scan build/try/clean-scan.json --tools-dir .tools --out build/try/vex.json
```

It logs `VEX assembly refused` with `stale VEX statement(s), no scan reported them`, naming the statement's vulnerability id, and exits 1. Then write a scan that does report the finding, and check the committed document against it:

```bash
cat > build/try/finding-scan.json <<'EOF'
{"SchemaVersion": 2, "Results": [{"Target": "x86_64/nats-server", "Vulnerabilities": [
  {"VulnerabilityID": "GO-2026-5932", "Severity": "UNKNOWN",
   "PkgIdentifier": {"PURL": "pkg:golang/golang.org/x/crypto@v0.57.0"}}]}]}
EOF
uv run python -m supplychain.vex --statements deploy/vex/statements.toml \
  --scan build/try/finding-scan.json --tools-dir .tools --out deploy/vex/sentinel.openvex.json --check
```

With both architectures' `nats-server` under `.tools/`, it logs `VEX evidence verified` once per binary, then `VEX document assembled`, and exits 0 without changing the file. With only the host's binary (all that `make tools` fetches), it logs `evidence does not hold: binary missing: .tools/aarch64/nats-server` and exits 1. The evidence check refuses to vouch for a binary it cannot read.

**Lint what CI lints.** These use the pinned linters, which `make supply-tools` fetches:

```bash
.tools/x86_64/actionlint -shellcheck .tools/x86_64/shellcheck
.tools/x86_64/shellcheck deploy/bundle/*.sh deploy/ansible/tests/*.sh
```

Silence and exit 0 mean clean.

**The deployment checks that need no Docker, no AWS and no host:**

```bash
unshare -rn uv run pytest -q tests/test_compose_stack.py tests/test_compose_config.py tests/test_compose_image.py \
  tests/test_compose_wiring.py tests/test_compose_smoke.py tests/test_deploy_env.py tests/compliance/test_deploy_conformance.py
cd deploy/ansible && cp inventory.example.ini inventory.ini && uvx --from ansible-core==2.21.4 ansible-playbook --syntax-check site.yml; cd -
make -n airgap-local
```

The tests pass. The syntax check prints `playbook: site.yml`, and `inventory.ini` is gitignored. The dry run prints the whole offline-install chain in order: build the console, build the bundle, fetch the supply-chain tools, sign with a throwaway key, then `verify_offline.sh` with that key.

**What needs a network the first time, and was not run for this chapter:** `make supply-tools` (cosign, syft, trivy, hadolint and the trust root), `make sbom`, `make scan`, `make vex`, `make bundle` (PyPI wheels for the target platform, plus `make web`), `make airgap-selftest` and `make airgap-local`. `make compose-up` and `make compose-smoke` need Docker, which was not available here.

### What has never run

These are stated plainly because the configuration exists and is checked, which makes it easy to assume it has run.

- **A tag release.** `release.yml` has never run. No artifact has been signed keyless, no SLSA provenance or SBOM attestation exists, and no container image has been built or scanned by it. It is checked statically by actionlint (with shellcheck), and every script it calls has been run locally.
- **CI on a hosted runner.** The repository has not been pushed, so no job in any workflow has run on GitHub. A CI job cited as evidence describes configuration.
- **The containers.** No image has been built or run, from either Dockerfile. `make compose-smoke`'s eight checks were proven against the process harness's real `nats-server`, Toxiproxy and sentinel processes, not against containers ([docs/compose.md](../compose.md), "What was verified, and where").
- **The aarch64 install.** The aarch64 leg of `airgap-install` needs an arm64 runner and has not run anywhere. The aarch64 bundle has never been installed.
- **The hosts.** `terraform apply` has not been run, the Ansible play has not run against a host, and the STIG role and its scan have not run.

## Design choices

**Pin every binary by sha256 in one lock, fetched by one function.** It buys a single answer to "which nats-server ran?", for CI, the harness and a bundle alike, and a mismatch writes nothing. It costs a hand edit and a re-hash for every upgrade. Terraform is not in the lock at all ([docs/deploy-aws.md](../deploy-aws.md)). Rejected: distro packages, whose versions differ by host and are absent in an enclave, and "latest" download URLs. [ADR-012](../system-design.md#adr-012--keyless-signing-verified-offline-against-a-pinned-trust-root).

**Keyless signing, verified offline against a pinned trust root.** It buys no key to guard or rotate, and a signer identity (this workflow at this tag) that an assessor can read. It costs a dependency on GitHub Actions and Sigstore's public-good service. When Sigstore rotates keys, the pinned root must be refreshed by hand, and verification fails closed until it is. Local runs cannot sign keyless, so the local proofs use key mode. Rejected: a long-lived release key (custody and rotation are the risk), and verifying online at install time, which defeats an air gap. [ADR-012](../system-design.md#adr-012--keyless-signing-verified-offline-against-a-pinned-trust-root).

**One verifier, run before unpacking, on every path.** It buys one policy to review and test (DRY): `make airgap-verify`, the offline proof, the release and Ansible all call `verify_signature.sh`. It costs bash, and a cosign binary that has to cross the gap and be checked against its pin. Rejected: unpacking first and checking `SHA256SUMS`, because that list sits inside the thing being verified. [ADR-012](../system-design.md#adr-012--keyless-signing-verified-offline-against-a-pinned-trust-root).

**A bundle of wheels, not only a container.** It buys an install on any glibc host that has Python 3.12, with no container runtime and no index, and it is the "one signed bundle" that [ADR-004](../system-design.md#adr-004--modular-monolith-with-an-internal-event-bus) promises the edge. It costs one build per architecture and a host Python requirement. The release image is built *from* the verified bundle, so the two do not drift. The Compose image builds from source, and `tests/test_compose_image.py` keeps it aligned with the release image.

**SLSA Build L2, stated as L2.** It buys a claim an assessor can check line by line. It costs the L3 guarantee: a workflow change could have the platform sign false provenance. Rejected for now: moving the build into an isolated reusable workflow. The partial measures (SHA-pinned actions, per-job permissions, no caches, a signing job that builds nothing) narrow the gap without closing it. [ADR-012](../system-design.md#adr-012--keyless-signing-verified-offline-against-a-pinned-trust-root).

**VEX only for real findings, with evidence re-checked, and no empty document.** It buys suppressions that cannot outlive their reason. When a scan stops reporting the finding, or the evidence stops holding, the build fails. It costs a gate that can fail on a new day with no code change, because the vulnerability database is not pinned, and that is RA-5 working as intended. Rejected: a blanket ignore list, and an "empty but valid" OpenVEX document, which the schema does not allow.

**Scan the container, but do not gate on it.** Base-image findings in the Chainguard layer are tracked through Chainguard's own advisories, and no Sentinel VEX process covers them yet. It is reported, not hidden, and listed as a limit in [docs/supply-chain.md](../supply-chain.md).

## How it fails

| Condition | What the code does | What you see |
|---|---|---|
| A malformed row in `deploy/tools.lock` | `parse` raises before any download | `tools.lock line N: expected 6 columns...` |
| A tool with no pin for the requested arch | `select` raises; nothing is fetched | `no pin for arch aarch64: <name>` |
| A download that does not match its pin | Logged with both digests; nothing written | `SHA-256 mismatch for <tool> <arch>: got ..., pinned ...` |
| A cached tool changed on disk | Not reused; downloaded again | With no network, a `URLError` traceback rather than a one-line message |
| `web/dist` not built | `build` exits before staging | `web/dist is missing: run make web first` |
| A shipped fixture missing from the source | The copy raises; the build fails | Python traceback naming the path |
| No `.sigstore.json` beside the bundle | Refused before cosign | `no signature bundle: ... (an unsigned artifact is never installed)` |
| No policy, or both | Refused before cosign | `no verification policy` or `ambiguous policy` |
| A trust root that is not the pinned one | Refused before cosign | `trusted root digest ... does not match the pinned ...` |
| A tampered, re-signed or wrong-identity bundle | cosign rejects it | `verify_signature: FAIL: signature does not verify for ...`; `verify_offline.sh` adds `bundle not unpacked` |
| A changed file inside the unpacked bundle | `sha256sum` fails; nothing installed | `<path>: FAILED`, `sha256sum: WARNING` |
| A file added inside the unpacked bundle | Refused; nothing installed | `install: refusing files that SHA256SUMS does not list:` |
| No `python3.12` on the host | Refused | `python3.12 is required on the host` |
| The proof's namespace has network | `verify_offline.sh` stops | `FAIL: namespace has network` |
| An SBOM missing a shipped component | Logged; exit 1 | `SBOM incomplete` with the missing names |
| A stale statement, failed evidence, or an out-of-date VEX file | `VexError`; exit 1 | `VEX check failed` with the reason |
| Findings left after VEX | Gate exit 5, script exit 1 | `Unaddressed vulnerabilities`, SARIF in `dist/scan/` |
| Trivy itself crashes | Exit 1, never read as a result | `Trivy scan failed` |
| No signature policy in Ansible | The play stops before copying anything | `No usable signature policy: ...` |
| A tag that is not the package version | The release `build` job fails | `tag vX does not match sentinel Y` |
| An action pinned by tag | `tests/test_workflows_pinned.py` fails | `<workflow>:<line> <action>@<tag>` |

## Check yourself

1. `fetch` writes two digests into each stamp file. Why is one not enough, and what went wrong when the stamp alone was trusted?

<details><summary>Answer</summary>

The first digest is the pin the download was checked against. The second is the digest of the file as written, which differs from the pin when the tool was extracted from an archive. On reuse, `fetch` recomputes `_stamp(pin, current bytes)` and compares, so a file changed after download no longer matches and is fetched again. When the stamp alone was trusted, a swapped binary was reused and copied into a bundle whose `BUNDLE.json` still quoted the pinned digest: the manifest lied without anyone editing it.

</details>

2. An attacker changes the tarball: they add a script to the bundle's console directory, regenerate `SHA256SUMS` inside it, and regenerate the `.sha256` beside it. Which step refuses the bundle, and why can `install.sh` not be the one?

<details><summary>Answer</summary>

`verify_signature.sh`, before anything is unpacked. The signature covers the tarball's bytes, and the attacker cannot produce a new one for the pinned identity or key. `install.sh` checks files against `SHA256SUMS`, but that list is inside the bundle, and the attacker rewrote it. The list is only trustworthy because the signature has already vouched for the tarball that carried it.

</details>

3. In keyless mode, why must `SENTINEL_CERT_IDENTITY` be the exact workflow at the tag, rather than "any certificate Fulcio issued"?

<details><summary>Answer</summary>

Fulcio issues a certificate to anyone with a valid OIDC token, for their own identity. A signature that verifies against the trust root proves only that *someone* signed it and that the signing was logged. The identity check is what says it was *this repository's* `release.yml` at *this tag*. A looser match would accept a signature made by any GitHub workflow in any repository.

</details>

4. Why does `GoPackageAbsent` refuse to pass when the control package is missing, even though the vulnerable package is also missing?

<details><summary>Answer</summary>

Because it then cannot tell "the package is not linked" from "I cannot see package paths in this file at all". The file might be compressed, the wrong file, or not a Go binary. Finding the path of a package that nats-server is known to link (bcrypt) proves the search can see paths, which makes the absence of `x/crypto/openpgp` meaningful.

</details>

5. The vulnerability database is not pinned, so the same commit can pass today and fail tomorrow. Is that a bug?

<details><summary>Answer</summary>

No. It is what vulnerability monitoring (RA-5) is for: a new advisory against something that ships should fail the gate until someone fixes it or writes a reviewed VEX statement with evidence. The cost is that the gate is not reproducible, so a red scan does not by itself mean the code changed. `docs/supply-chain.md` states this as a limit.

</details>

6. What does SLSA Build L2 let an assessor conclude about a Sentinel release, and what attack does it leave open?

<details><summary>Answer</summary>

That a hosted platform (GitHub Actions) built the artifact and signed a provenance statement naming the repository, commit, workflow and trigger, and that the statement is authentic. It does not rule out a malicious or compromised change to the repository's own workflow having the platform sign provenance for content it did not build. The provenance is generated by the tenant's own workflow, not by an isolated builder. That is the L3 gap.

</details>

7. Every job in `ci.yml` already runs `uv sync --locked`. Why does the workflow also set `UV_LOCKED: "1"`?

<details><summary>Answer</summary>

`uv sync --locked` protects only the install step. A later `uv run` re-locks silently when `uv.lock` is out of date with `pyproject.toml`, and would then test dependencies nobody reviewed. With `UV_LOCKED=1`, every uv command fails on a stale lock instead. `unlocked_uv_jobs` in `tests/test_workflows_pinned.py` makes this a rule for every job that sets up uv.

</details>

8. `docs/traceability.md` shows REQ-DEP-002 (the offline install on both architectures) as verified. What has actually been demonstrated for aarch64?

<details><summary>Answer</summary>

Nothing has run. The requirement is verified by two `ci` evidence items, the `airgap-install` job and its `make airgap-local` step, and the trace checks only that they exist in `ci.yml`. The x86_64 install has been run locally. The aarch64 leg needs an arm64 runner and has not run anywhere, and CI itself has never run because the repository has not been pushed. Chapter 13 explains why "verified" in the trace means the evidence exists, not that it passed.

</details>

## Where next

- [Chapter 13: Keeping it honest](13-guardrails-compliance-mbse.md): the test ladder, the doc guards, the OSCAL package these controls feed, and the SysML trace that cites the `airgap-install` job.
- [Chapter 14: End to end](14-end-to-end.md): one CDM through a node installed this way.
- [docs/supply-chain.md](../supply-chain.md): the release assets, the online and offline verification commands, and the control mapping (SI-7, CM-8, CM-14, RA-5, SR-4, SR-11, SA-10).
- [docs/install-guide.md](../install-guide.md): the one-page procedure for the person at the disconnected site.
- [docs/compose.md](../compose.md) and [docs/deploy-aws.md](../deploy-aws.md): the container stack and the AWS hub.
- [docs/system-design.md](../system-design.md), ADR-012 and ADR-004.
