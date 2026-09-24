#!/usr/bin/env bash
# Prove the offline signature path with the real, pinned cosign and no network.
#
#   deploy/bundle/selftest_signature.sh        (make airgap-selftest)
#
# Every sign and verify below runs inside `unshare -rn` (loopback only).
# Key mode, with an ephemeral key pair made in a temp dir and deleted:
#   good signature verifies; tampered artifact, another key's signature,
#   missing signature bundle and missing policy are all rejected.
# Keyless mode, against a real Sigstore public-good signature (cosign's own
# release binary, signed by the Sigstore project) and the pinned trusted root:
#   verifies offline; wrong identity and a trusted root that does not match
#   its pin are rejected. This is the path a release artifact takes.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
ARCH=$(uname -m); ARCH=${ARCH/arm64/aarch64}; ARCH=${ARCH/amd64/x86_64}
export COSIGN=${COSIGN:-$REPO/.tools/$ARCH/cosign}
TRUSTED_ROOT=$REPO/.tools/noarch/sigstore-trusted-root.json
ROOT_PIN=$(awk '$1 == "sigstore-trusted-root.json" {print $4}' "$REPO/deploy/tools.lock")
VERIFY="$HERE/verify_signature.sh"

for f in "$COSIGN" "$COSIGN.sigstore.json" "$TRUSTED_ROOT"; do
  [[ -f "$f" ]] || { echo "selftest: missing $f - run: uv run python scripts/fetch_tools.py cosign cosign.sigstore.json sigstore-trusted-root.json" >&2; exit 1; }
done

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
offline() { unshare -rn env HOME="$WORK/home" "$@"; }
mkdir -p "$WORK/home"
if offline bash -c 'exec 3<>/dev/tcp/1.1.1.1/443' 2>/dev/null; then
  echo "selftest: FAIL - the namespace has network" >&2; exit 1
fi

failures=0
expect() {  # expect pass|fail "<label>" "<stderr text on fail>" artifact [ENV=VALUE ...]
  local want=$1 label=$2 needle=$3 artifact=$4; shift 4
  local out rc=0
  out=$(offline env -u SENTINEL_VERIFY_KEY -u SENTINEL_TRUSTED_ROOT -u SENTINEL_CERT_IDENTITY \
        "$@" bash "$VERIFY" "$artifact" 2>&1) || rc=$?
  if [[ $want == pass && $rc -eq 0 ]] || [[ $want == fail && $rc -ne 0 && $out == *"$needle"* ]]; then
    echo "  ok    $label"
  else
    echo "  WRONG $label (exit $rc)"; echo "$out" | sed 's/^/        /'; failures=$((failures + 1))
  fi
}

echo "==> key mode: ephemeral key pair, no transparency log"
mkdir -p "$WORK/a/payload" && echo "sentinel selftest" > "$WORK/a/payload/VERSION"
tar -czf "$WORK/a/bundle.tar.gz" -C "$WORK/a" payload
offline bash "$HERE/sign_local.sh" --pubkey-out "$WORK/a/local.pub" "$WORK/a/bundle.tar.gz" >/dev/null
expect pass "good signature verifies" "" "$WORK/a/bundle.tar.gz" SENTINEL_VERIFY_KEY="$WORK/a/local.pub"

mkdir "$WORK/t" && cp "$WORK/a/bundle.tar.gz" "$WORK/a/bundle.tar.gz.sigstore.json" "$WORK/t/"
printf 'x' >> "$WORK/t/bundle.tar.gz"
expect fail "tampered artifact is rejected" "FAIL: signature" "$WORK/t/bundle.tar.gz" SENTINEL_VERIFY_KEY="$WORK/a/local.pub"

mkdir "$WORK/k" && cp "$WORK/a/bundle.tar.gz" "$WORK/k/"
offline bash "$HERE/sign_local.sh" --pubkey-out "$WORK/k/other.pub" "$WORK/k/bundle.tar.gz" >/dev/null
expect fail "signature by another key is rejected" "FAIL: signature" "$WORK/k/bundle.tar.gz" SENTINEL_VERIFY_KEY="$WORK/a/local.pub"

mkdir "$WORK/m" && cp "$WORK/a/bundle.tar.gz" "$WORK/m/"
expect fail "missing signature bundle is rejected" "no signature bundle" "$WORK/m/bundle.tar.gz" SENTINEL_VERIFY_KEY="$WORK/a/local.pub"
expect fail "no verification policy is rejected" "no verification policy" "$WORK/a/bundle.tar.gz"

echo "==> keyless mode: Sigstore public-good signature, pinned trusted root, offline"
SIGNER=keyless@projectsigstore.iam.gserviceaccount.com
GOOGLE=https://accounts.google.com
expect pass "cosign's own release signature verifies offline" "" "$COSIGN" \
  SENTINEL_TRUSTED_ROOT="$TRUSTED_ROOT" SENTINEL_TRUSTED_ROOT_SHA256="$ROOT_PIN" \
  SENTINEL_CERT_IDENTITY="$SIGNER" SENTINEL_CERT_ISSUER="$GOOGLE"
expect fail "wrong signer identity is rejected" "FAIL: signature" "$COSIGN" \
  SENTINEL_TRUSTED_ROOT="$TRUSTED_ROOT" SENTINEL_CERT_IDENTITY="attacker@example.com" SENTINEL_CERT_ISSUER="$GOOGLE"
expect fail "trusted root not matching its pin is rejected" "trusted root digest" "$COSIGN" \
  SENTINEL_TRUSTED_ROOT="$TRUSTED_ROOT" SENTINEL_TRUSTED_ROOT_SHA256="$(printf '0%.0s' {1..64})" \
  SENTINEL_CERT_IDENTITY="$SIGNER" SENTINEL_CERT_ISSUER="$GOOGLE"

if (( failures )); then echo "selftest: FAIL ($failures unexpected outcomes)" >&2; exit 1; fi
echo "PASS: offline signature verification (key and keyless) accepts only what it should"
