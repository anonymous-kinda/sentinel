#!/usr/bin/env bash
# Verify a Sentinel release artifact's signature. Fails closed. Needs no network.
#
#   verify_signature.sh <artifact>          # expects <artifact>.sigstore.json beside it
#
# Exactly one verification policy must be set:
#
#   Keyless (release artifacts, signed in GitHub Actions via Sigstore):
#     SENTINEL_TRUSTED_ROOT         Sigstore trusted_root.json (Fulcio CA, Rekor, CT, TSA keys)
#     SENTINEL_CERT_IDENTITY        exact signer, e.g.
#       https://github.com/OWNER/sentinel/.github/workflows/release.yml@refs/tags/v0.2.0
#     SENTINEL_CERT_ISSUER          default https://token.actions.githubusercontent.com
#     SENTINEL_TRUSTED_ROOT_SHA256  optional: pinned digest of the trusted root, checked first
#
#   Key (a site key, e.g. an enclave countersignature, or the local proof):
#     SENTINEL_VERIFY_KEY           PEM public key. No transparency log exists for
#                                   such signatures, so the tlog check is skipped (and said so).
#
# COSIGN selects the cosign binary (default: cosign on PATH). The cosign
# binary is itself pinned by sha256 in deploy/tools.lock. With the trusted
# root local, cosign verifies the certificate chain, the signed certificate
# timestamp and the Rekor inclusion proof offline (docs/supply-chain.md).
set -euo pipefail

die() { echo "verify_signature: $*" >&2; exit 1; }

ARTIFACT=${1:?usage: verify_signature.sh <artifact>}
COSIGN=${COSIGN:-cosign}
BUNDLE="$ARTIFACT.sigstore.json"
ISSUER=${SENTINEL_CERT_ISSUER:-https://token.actions.githubusercontent.com}

[[ -f "$ARTIFACT" ]] || die "artifact not found: $ARTIFACT"
[[ -f "$BUNDLE" ]] || die "no signature bundle: $BUNDLE (an unsigned artifact is never installed)"

KEY=${SENTINEL_VERIFY_KEY:-}
ROOT=${SENTINEL_TRUSTED_ROOT:-}
IDENTITY=${SENTINEL_CERT_IDENTITY:-}

if [[ -n "$KEY" && ( -n "$ROOT" || -n "$IDENTITY" ) ]]; then
  die "ambiguous policy: set SENTINEL_VERIFY_KEY or SENTINEL_TRUSTED_ROOT + SENTINEL_CERT_IDENTITY, not both"
elif [[ -n "$KEY" ]]; then
  [[ -f "$KEY" ]] || die "public key not found: $KEY"
  echo "verify_signature: key mode - a site key has no transparency log entry; tlog check skipped" >&2
  POLICY=(--key "$KEY" --insecure-ignore-tlog)
elif [[ -n "$ROOT" || -n "$IDENTITY" ]]; then
  [[ -f "$ROOT" ]] || die "trusted root not found: ${ROOT:-<unset SENTINEL_TRUSTED_ROOT>}"
  [[ -n "$IDENTITY" ]] || die "keyless mode needs SENTINEL_CERT_IDENTITY (the exact signing workflow)"
  if [[ -n "${SENTINEL_TRUSTED_ROOT_SHA256:-}" ]]; then
    actual=$(sha256sum "$ROOT" | cut -d' ' -f1)
    [[ "$actual" == "$SENTINEL_TRUSTED_ROOT_SHA256" ]] \
      || die "trusted root digest $actual does not match the pinned $SENTINEL_TRUSTED_ROOT_SHA256"
  fi
  POLICY=(--trusted-root "$ROOT" --certificate-identity "$IDENTITY" --certificate-oidc-issuer "$ISSUER")
else
  die "no verification policy: set SENTINEL_TRUSTED_ROOT + SENTINEL_CERT_IDENTITY (keyless) or SENTINEL_VERIFY_KEY"
fi

if ! "$COSIGN" verify-blob --bundle "$BUNDLE" "${POLICY[@]}" "$ARTIFACT"; then
  echo "verify_signature: FAIL: signature does not verify for $(basename "$ARTIFACT")" >&2
  exit 1
fi
echo "verify_signature: OK $(basename "$ARTIFACT") ($(sha256sum "$ARTIFACT" | cut -d' ' -f1))"
