# Software supply chain

This page lists what a Sentinel release contains, what signs each part, and what attests to it. It gives the exact commands to verify a release online and with no network at all, and it maps each claimed NIST SP 800-53 control to the files that implement and prove it. The same rule applies here as everywhere else in Sentinel: **an input that would make the answer wrong is refused, not warned about.** An unsigned bundle is not installed. A VEX statement that answers no real finding is not published. An SBOM that misses a shipped component fails the build.

## What a release contains

`.github/workflows/release.yml` runs on a `vX.Y.Z` tag. The tag must equal `sentinel.__version__`. The workflow produces a **draft** GitHub release, which a maintainer publishes.

| Asset | What it is | Protected by |
|---|---|---|
| `sentinel-<ver>-<arch>.tar.gz` (x86_64, aarch64) | Air-gap bundle: wheels, hash-locked `requirements.txt`, pinned `uv` and `nats-server`, console, NASA fixtures, `install.sh`, `BUNDLE.json`, per-file `SHA256SUMS` | Keyless cosign signature (`.sigstore.json`), SLSA provenance, SBOM attestations, `.sha256` |
| `sentinel-<ver>-<arch>.container.tar` | Container image archive (`docker load` / `podman load`) built from that bundle | Keyless cosign signature, SLSA provenance, SBOM attestations |
| `sentinel-python-runtime.{spdx,cdx}.json` | SBOM of the Python runtime | `SHA256SUMS` (signed), SBOM attestation (SPDX) |
| `sentinel-web-console.{spdx,cdx}.json` | SBOM of the web console | `SHA256SUMS` (signed), SBOM attestation (SPDX) |
| `sentinel.openvex.json` | Reviewed OpenVEX statements | `SHA256SUMS` (signed) |
| `trusted_root.json` | The Sigstore trust root used for offline verification | `SHA256SUMS` (signed) **and** its pin in `deploy/tools.lock` |
| `SHA256SUMS` | Digests of all the assets above | Keyless cosign signature |
| `*.sigstore.json` | One Sigstore bundle per signature: signature, Fulcio certificate, Rekor inclusion proof, RFC 3161 timestamp | Self-verifying against `trusted_root.json` |
| `provenance.intoto.sigstore.json`, `sbom-*.intoto.sigstore.json` | The attestations themselves, so they can be verified offline | Self-verifying against `trusted_root.json` |

### Signed, and by whom

Every tarball, every image archive, and `SHA256SUMS` are signed with `cosign sign-blob --bundle`. The signing is **keyless**. The job's GitHub OIDC token obtains a short-lived Fulcio certificate that names the signing workflow. The signature is logged in the public Rekor transparency log and timestamped by Sigstore's TSA. No long-lived signing key exists. The signer identity is exactly:

```
https://github.com/OWNER/sentinel/.github/workflows/release.yml@refs/tags/vX.Y.Z
issuer: https://token.actions.githubusercontent.com
```

Signing SHA256SUMS extends the signature to the SBOMs, the VEX document and the trust root. The `sign` job holds the only `id-token: write` permission, and it runs no build code. It downloads the finished artifacts, signs them, and then **verifies every signature offline** inside `unshare -rn` against the pinned trusted root and the exact identity. Only then are the artifacts uploaded. A signature that would not verify in an enclave fails the release.

### Attested

- **Build provenance.** `actions/attest-build-provenance` produces a SLSA v1 provenance statement for the tarballs and image archives: repository, commit, workflow, runner, and trigger.
- **SBOMs.** `actions/attest-sbom` binds the SPDX SBOMs of the Python runtime and the web console to the same subjects.

As of v4, both actions are thin wrappers over `actions/attest`, which takes the same inputs. Moving to it later is a one-line change per step.

## SLSA level: Build L2, and why not L3

**Claimed: SLSA v1.0 Build L2.**

- **L1:** provenance exists, and it describes how each artifact was built.
- **L2:** the build runs on a hosted platform (GitHub-hosted runners). The platform generates the provenance and signs it with a certificate bound to the workflow identity, so consumers can check that it is authentic.

**Not L3.** Build L3 requires provenance that the tenant's own build steps cannot forge, with builds isolated from each other. Here the provenance is generated inside this repository's own workflow. Anyone who can change `release.yml`, or a compromised step in the `sign` job, could get the platform to sign provenance for content it did not build. Reaching L3 on GitHub means moving the build into an isolated, trusted reusable workflow. Verifiers would then pin that workflow (`gh attestation verify --signer-workflow ...`).

These measures narrow the gap without closing it:

- Every third-party action is pinned by full commit SHA (`tests/test_workflows_pinned.py`).
- `permissions: {}` is set at the top of the workflow and granted per job.
- No dependency caches are restored in a release.
- The only job with signing rights runs no build code.
- Runners are ephemeral.

**Reproducibility** is a separate, independent check. The bundle is byte-reproducible: sorted entries, root ownership, normalised modes, and every timestamp set to `SOURCE_DATE_EPOCH`, which defaults to the commit time, including the gzip header and the wheel's zip entries. Two builds at the same commit, with a fresh `npm run build` in between, gave identical SHA-256 digests on the development machine. Reproducibility across machines (different zlib or Python builds) has **not** been checked yet. `BUNDLE.json` records `source_tree: clean|dirty`, so a bundle built from uncommitted changes cannot pass as that commit.

## Verify a release online

The commands below need the Sigstore and GitHub APIs. They run outside this repo's test suite.

```bash
VER=0.2.0; REPO=OWNER/sentinel
ID="https://github.com/$REPO/.github/workflows/release.yml@refs/tags/v$VER"

# Signature; cosign fetches the trust root through TUF
cosign verify-blob --bundle sentinel-$VER-x86_64.tar.gz.sigstore.json \
  --certificate-identity "$ID" --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  sentinel-$VER-x86_64.tar.gz

# Provenance and SBOM attestations, from GitHub's attestation store
gh attestation verify sentinel-$VER-x86_64.tar.gz --repo $REPO \
  --signer-workflow $REPO/.github/workflows/release.yml
gh attestation verify sentinel-$VER-x86_64.tar.gz --repo $REPO --predicate-type https://spdx.dev/Document/v2.3
```

## Verify a release offline (air gap)

**What crosses the gap:**

- The assets listed above.
- `deploy/bundle/verify_signature.sh`, and `verify_offline.sh` for the full proof.
- A cosign binary for the enclave's architecture, brought in through the site's software approval process.

On the enclave, nothing needs a network.

```bash
VER=0.2.0; ARCH=x86_64
ID="https://github.com/OWNER/sentinel/.github/workflows/release.yml@refs/tags/v$VER"

# 0. The verifier. The cosign binary must match its pin in deploy/tools.lock
#    (cosign 3.1.3, cosign-linux-amd64):
echo "4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71  cosign" | sha256sum --strict -c -

# 1. The trust anchor. The release's trusted_root.json must equal the pinned Sigstore root
#    (sigstore-trusted-root.json in deploy/tools.lock; obtained through TUF, see "Trust root"):
echo "6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66  trusted_root.json" | sha256sum --strict -c -

# 2. The bundle's signature, inside a namespace with no network:
COSIGN=./cosign SENTINEL_TRUSTED_ROOT=trusted_root.json \
SENTINEL_TRUSTED_ROOT_SHA256=6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66 \
SENTINEL_CERT_IDENTITY="$ID" \
  unshare -rn ./verify_signature.sh sentinel-$VER-$ARCH.tar.gz
#    ...which runs exactly:
#    cosign verify-blob --bundle sentinel-$VER-$ARCH.tar.gz.sigstore.json --trusted-root trusted_root.json \
#      --certificate-identity "$ID" --certificate-oidc-issuer https://token.actions.githubusercontent.com \
#      sentinel-$VER-$ARCH.tar.gz

# 3. Everything else, through the signed checksum list:
COSIGN=./cosign SENTINEL_TRUSTED_ROOT=trusted_root.json SENTINEL_CERT_IDENTITY="$ID" \
  unshare -rn ./verify_signature.sh SHA256SUMS && sha256sum --strict -c SHA256SUMS

# 4. Provenance, offline:
./cosign verify-blob-attestation --bundle provenance.intoto.sigstore.json --trusted-root trusted_root.json \
  --certificate-identity "$ID" --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --type https://slsa.dev/provenance/v1 sentinel-$VER-$ARCH.tar.gz

# 5. The full proof: signature, then install, then run the node and reproduce the NASA validation, all with no network:
COSIGN=./cosign SENTINEL_TRUSTED_ROOT=trusted_root.json SENTINEL_CERT_IDENTITY="$ID" \
  ./verify_offline.sh sentinel-$VER-$ARCH.tar.gz
```

With the trust root on local disk, cosign checks the whole chain offline:

- the Fulcio certificate chain;
- the signed certificate timestamp;
- the Rekor inclusion proof and signed entry timestamp;
- the TSA timestamp;
- the signature over the artifact digest;
- the certificate's identity and issuer.

Steps 0–3 and 5 are exercised by this repo, as described in the next section. Step 4 runs only on a real release, because a local run has no GitHub-signed attestation to check.

**Site key (countersignature).** An enclave that re-signs approved software with its own key, for example after its own review or with an HSM-held key, uses the same verifier with `SENTINEL_VERIFY_KEY=site.pub`. A private key's signature has no transparency-log entry, so the verifier skips the tlog check and says so on stderr. Supplying both policies at once is refused as ambiguous.

**Ansible.** The `sentinel` role runs this same gate on the target host before anything is unpacked (`deploy/ansible/roles/sentinel/tasks/verify.yml`). In order, it:

1. copies the pinned cosign for the target's architecture and checks its sha256 on the host against `deploy/tools.lock`;
2. copies the trust anchor;
3. runs `verify_signature.sh`.

Without `sentinel_repository` (keyless) or `sentinel_verify_mode=key` plus `sentinel_verify_key`, the play stops.

```bash
uv run python scripts/fetch_tools.py --arch aarch64 cosign sigstore-trusted-root.json
ansible-playbook -i inventory.ini site.yml -e sentinel_repository=OWNER/sentinel
```

## What this repo proves locally, and CI proves on every push

| Command | What it proves |
|---|---|
| `make airgap-selftest` | Real pinned cosign, every step inside `unshare -rn`. Key mode: a good signature verifies; a tampered artifact, another key's signature, a missing signature bundle and a missing policy are rejected. Keyless mode: a real Sigstore public-good signature (cosign's own release binary, signed by the Sigstore project) verifies offline against the pinned trusted root; a wrong identity and a trust root that does not match its pin are rejected. The self-test catches a lying verifier: with a cosign whose `verify-blob` always exits 0, it reports 3 WRONG and fails. |
| `make airgap-local` | Builds the bundle and signs it with an ephemeral key pair (`sign-local`: made in a mode-700 temp dir, random password, no transparency-log upload, private key deleted on exit, never committed). Then runs `airgap-verify VERIFY_KEY=...`: signature, install and run, with no network. |
| `make airgap-verify` on a tampered bundle | Rejected with `FAIL: signature verification - bundle not unpacked`. The same happens when the attacker also regenerates `SHA256SUMS` and `.sha256`. Before M4, that tampered bundle installed and passed. |
| `deploy/ansible/tests/test_verify.sh` | The Ansible gate on localhost: a good local signature passes; a tampered bundle (with a regenerated `.sha256`) and a missing policy are refused; the keyless branch verifies a real Sigstore signature and refuses another identity. |
| `pytest tests/supplychain` | Policy logic of the verifier (stub cosign), pins, checksums, reproducible tarball, bundle manifest, SBOM gate, Trivy reader, VEX rules and evidence. No network. |

**CI uses keyless signing.** Local runs cannot: there is no GitHub OIDC token outside Actions. That is why the local end-to-end proof uses the key path, and why the self-test exercises the keyless verify path against a real public-good signature instead.

## SBOMs

`make sbom` writes SPDX 2.3 JSON and CycloneDX JSON to `dist/sbom/`, generated by syft 1.52.0 (pinned).

- **Python runtime (`sentinel-python-runtime`).** Built from the hash-locked runtime set (`uv export --no-dev`: no dev tools, no optional AI extras) plus the sentinel wheel. It is installed for CPython 3.12 manylinux, the bundle's target, and catalogued from the installed metadata. That means environment markers resolve exactly as they do in the bundle: numpy 2.5.3, not both locked numpy versions. It has 25 components with licences. Component versions are identical for x86_64, aarch64 and the container's CPython 3.14. Per-file wheel digests differ by architecture; they are listed in each bundle's `BUNDLE.json` and `SHA256SUMS`.
- **Web console (`sentinel-web-console`).** The production dependency closure of `web/package-lock.json` (34 components). syft excludes devDependencies, so this is what Vite bundles into `web/dist`.
- **Gate.** An SBOM with no components, or one missing a component known to ship (sentinel, numpy, scipy, fastapi, cryptography, skyfield; react, react-dom, cesium), fails the run.
- **Other inventories.** The bundled third-party binaries (`uv`, `nats-server`) are inventoried by `BUNDLE.json` (upstream URL, version, sha256) and `deploy/tools.lock`. Trivy catalogues their embedded Go and Rust module lists during the scan.

## Vulnerability scanning and the VEX process

`make scan` (in CI on every push to main and every pull request, and gating in the release):

1. **Raw scans, nothing suppressed.**
   - `trivy fs .` reads `uv.lock` and `web/package-lock.json`. For Python this means **every** locked package, including dev tools and the optional AI extras, a superset of what ships. For npm it means production dependencies only.
   - `trivy rootfs` scans the `nats-server` and `uv` binaries that ship, for both architectures, exactly as pinned.
2. **VEX check.** Each reviewed statement in `deploy/vex/statements.toml` must meet four conditions, or the run fails:
   - it answers a finding the raw scan actually reported; a statement nothing reports any more is "stale" and must be removed;
   - it uses an OpenVEX status and, for `not_affected`, both a justification from the OpenVEX vocabulary and a written impact statement;
   - it has no unknown keys (a typo is an error, not a silent omission);
   - its **evidence check** still holds against the shipped binaries.

   `deploy/vex/sentinel.openvex.json` is generated from the statements (`make vex`). `make scan` fails if the committed copy is out of date.
3. **Gate.** SARIF scans run with the VEX document applied. **Any** finding left fails, at any severity. The gate exits 5, distinct from Trivy's own error exit (1), so a crashed scan never reads as a pass or a finding.

Telemetry and version checks are disabled (`--disable-telemetry --skip-version-check`). The vulnerability database is Trivy's current one and is **not pinned**: the same commit can pass today and fail tomorrow. That is RA-5 working as intended.

**Current finding and statement.** The raw scan reports one finding: **GO-2026-5932** in `golang.org/x/crypto v0.57.0`, inside `nats-server v2.15.0`, on both architectures. The advisory covers the unmaintained `x/crypto/openpgp` package; it has no fixed version, and Trivy matches it at module level. The statement is `not_affected / vulnerable_code_not_present`. The evidence check (`supplychain/evidence.py`) confirms it on every scan: neither shipped `nats-server` binary contains any `golang.org/x/crypto/openpgp` symbol in its function table, while a positive control is present (`golang.org/x/crypto/bcrypt`, which nats-server does link). An absence check that cannot see the control fails instead of passing. Without the VEX document, the gate fails with 2 results (both architectures). With it, the gate passes. The source lockfiles have 0 findings.

**Empty VEX.** The OpenVEX 0.2.0 JSON schema requires at least one statement (`minItems: 1`), so an "empty but valid" document does not exist. With no statements, `make vex` deletes the document, and the scan runs without `--vex`.

**Container image.** The release scans each image archive with `trivy image` and uploads the SARIF. That scan is **reported, not gated**: base-image findings in the Chainguard layer are tracked through Chainguard's own advisories, and no Sentinel VEX process covers them yet.

## Container

`deploy/containers/Dockerfile`:

- **Build context.** An unpacked, signature-verified bundle. The builder re-checks its `SHA256SUMS`, then installs the same hash-locked dependency set (`--require-hashes`, binary wheels only) and the bundle's sentinel wheel.
- **Runtime.** `cgr.dev/chainguard/python:latest` (no shell, no package manager), as UID 65532. `/var/lib/sentinel` is the only writable path, so the container runs with `--read-only`.
- **Pins.** Both bases are pinned by digest, resolved from the registry with the pinned crane.
- **Python version.** Chainguard's free tags track the newest CPython (3.14 at these digests), so the cp314 wheels come from PyPI at build time, checked against the same lock hashes.
- **Checked here.** hadolint is clean. The build and run steps, replayed without Docker on CPython 3.14 from the real bundle, installed with every hash checked and reproduced the NASA validation offline, writing nothing outside `SENTINEL_VAR`. The image itself is built and smoke-tested in the release workflow on both architectures: read-only root, `--cap-drop ALL`, non-root user.

## Trust root

The offline verifier's trust anchor is Sigstore's public-good `trusted_root.json`. It holds the Fulcio CA, Rekor, CT log and TSA keys, and it is pinned by sha256 in `deploy/tools.lock`. The pinned file was obtained through cosign's TUF client, which verifies the file from cosign's embedded TUF root (TUF targets v14). The CDN serves it content-addressed. When Sigstore rotates keys, a new signature may stop verifying against the pinned root. The release's own offline verification step then fails loudly. To refresh the pin:

```bash
export TUF_ROOT=$(mktemp -d)
.tools/x86_64/cosign initialize                    # TUF-verified download into $TUF_ROOT
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["signed"]["version"])' \
  "$TUF_ROOT/tuf-repo-cdn.sigstore.dev/targets.json"
sha256sum "$TUF_ROOT/tuf-repo-cdn.sigstore.dev/targets/trusted_root.json"
# update the sigstore-trusted-root.json row in deploy/tools.lock: version targets-v<N>, the sha256,
# URL https://tuf-repo-cdn.sigstore.dev/targets/<sha256>.trusted_root.json
```

## Control mapping

| Control | What Sentinel does | Evidence |
|---|---|---|
| **SI-7** Software, Firmware, and Information Integrity | Every release artifact is signed. The signature is verified before unpacking on every install path (Make, air gap, Ansible). Per-file `SHA256SUMS` and hash-locked wheels are checked at install. Tampering, including a regenerated checksum, is rejected. | `deploy/bundle/verify_signature.sh`, `deploy/bundle/verify_offline.sh`, `deploy/bundle/install.sh`, `deploy/ansible/roles/sentinel/tasks/verify.yml`, `deploy/bundle/selftest_signature.sh`, `deploy/ansible/tests/test_verify.sh`, `tests/supplychain/test_verify_signature.py`, `tests/supplychain/test_checksums.py` |
| **CM-8** System Component Inventory | SPDX and CycloneDX SBOMs for the Python runtime and web console, gated for completeness. `BUNDLE.json` lists the pinned binaries and every wheel digest. `deploy/tools.lock` pins every third-party binary. | `scripts/sbom.py`, `supplychain/sbom.py`, `supplychain/bundle.py`, `deploy/tools.lock`, release assets `*.spdx.json` / `*.cdx.json`, `tests/supplychain/test_sbom.py`, `tests/supplychain/test_bundle.py` |
| **CM-14** Signed Components | Installation refuses a component without a signature from the approved identity or key. A missing, ambiguous or incomplete policy is refused before cosign runs. Releases are signed keyless in CI. | `deploy/bundle/verify_signature.sh`, `deploy/ansible/roles/sentinel/tasks/verify.yml`, `deploy/ansible/roles/sentinel/defaults/main.yml`, `.github/workflows/release.yml` (`sign` job), `tests/supplychain/test_verify_signature.py` |
| **RA-5** Vulnerability Monitoring and Scanning | Trivy scans the source lockfiles and the shipped binaries on every push to main, every pull request and every release. Any unaddressed finding fails. VEX statements are allowed only for real findings, with justification and re-checked evidence. SARIF goes to code scanning; container images are scanned and reported. | `scripts/scan.py`, `supplychain/trivy.py`, `supplychain/vex.py`, `supplychain/evidence.py`, `deploy/vex/statements.toml`, `deploy/vex/sentinel.openvex.json`, `.github/workflows/ci.yml` (`supply-chain`), `.github/workflows/release.yml` (`build`, `container`, `code-scanning`), `tests/supplychain/test_vex.py`, `tests/supplychain/test_evidence.py`, `tests/supplychain/test_trivy.py` |
| **SR-4** Provenance | SLSA v1 build provenance (Build L2) and SBOM attestations for every tarball and image, shipped as files so they verify offline. `BUNDLE.json` records the commit, clean or dirty tree, and epoch. `tools.lock` records the upstream URL and sha256 of every third-party binary. | `.github/workflows/release.yml` (`attest-build-provenance`, `attest-sbom`), `provenance.intoto.sigstore.json`, `supplychain/bundle.py`, `deploy/tools.lock` |
| **SR-11** Component Authenticity | Third-party binaries and trust material are verified against sha256 pins before use; a mismatch writes nothing. cosign is re-checked on the target host. GitHub Actions are pinned by commit SHA and container bases by registry digest. The Sigstore trust root is pinned. | `supplychain/toolslock.py`, `scripts/fetch_tools.py`, `deploy/tools.lock`, `deploy/ansible/roles/sentinel/tasks/verify.yml`, `.github/workflows/release.yml`, `deploy/containers/Dockerfile`, `tests/supplychain/test_toolslock.py`, `tests/test_workflows_pinned.py` |
| **SA-10** Developer Configuration Management | Releases come only from a tag equal to the package version and end as a draft for maintainer review. The bundle is byte-reproducible per commit and marks a dirty tree. Workflows, container and deploy scripts are linted in CI (actionlint with shellcheck, hadolint, shellcheck). | `scripts/build_bundle.py`, `supplychain/bundle.py`, `tests/supplychain/test_bundle.py`, `.github/workflows/release.yml`, `.github/workflows/ci.yml` (`release-lint`) |

## Limits (what is not claimed)

- **SLSA Build L3.** See above.
- **Correctness.** A valid signature proves who built an artifact and that it is unchanged. It says nothing about whether the source is correct; the test ladder and the validation report cover that.
- **Unpinned vulnerability database.** Scan results depend on the day of the scan.
- **Cross-machine reproducibility** is not yet demonstrated.
- **Build toolchain.** npm devDependencies (Vite, TypeScript, Vitest) shape `web/dist` but are neither in the web SBOM nor scanned.
- **Container image findings** are reported, not gated.
- **Key-mode signatures** (local proof, site keys) have no transparency-log entry, by construction.
- **`release.yml` runs only on GitHub.** Here it is validated statically (actionlint with shellcheck), and every script it calls is exercised locally.
