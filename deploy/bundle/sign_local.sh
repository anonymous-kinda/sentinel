#!/usr/bin/env bash
# Sign artifacts with an ephemeral local key pair: the offline stand-in for CI.
#
#   sign_local.sh [--pubkey-out dist/local-signing-key.pub] <artifact>...
#
# Writes <artifact>.sigstore.json beside each artifact and the PUBLIC key to
# --pubkey-out. The private key is generated in a mode-700 temp dir,
# encrypted with a random password that is never stored, used, and deleted
# on exit: it is never committed and cannot be reused. The signing config
# lists no Fulcio, Rekor or TSA service, so nothing leaves the machine.
#
# Release artifacts are NOT signed this way: CI signs keyless (Sigstore,
# GitHub OIDC), see .github/workflows/release.yml and docs/supply-chain.md.
set -euo pipefail

COSIGN=${COSIGN:-cosign}
PUB_OUT=dist/local-signing-key.pub
if [[ "${1:-}" == "--pubkey-out" ]]; then PUB_OUT=${2:?--pubkey-out needs a path}; shift 2; fi
(( $# > 0 )) || { echo "usage: sign_local.sh [--pubkey-out PATH] <artifact>..." >&2; exit 1; }

KEYDIR=$(mktemp -d)
trap 'rm -rf "$KEYDIR"' EXIT
chmod 700 "$KEYDIR"
COSIGN_PASSWORD=$(head -c 32 /dev/urandom | base64)
export COSIGN_PASSWORD
(cd "$KEYDIR" && "$COSIGN" generate-key-pair --output-key-prefix ephemeral >/dev/null 2>&1) \
  || { echo "sign_local: cosign could not generate a key pair" >&2; exit 1; }
cat > "$KEYDIR/signing_config.json" <<'JSON'
{"mediaType": "application/vnd.dev.sigstore.signingconfig.v0.2+json",
 "caUrls": [], "oidcUrls": [], "rekorTlogUrls": [], "tsaUrls": [],
 "rekorTlogConfig": {"selector": "ANY"}, "tsaConfig": {"selector": "ANY"}}
JSON

for artifact in "$@"; do
  [[ -f "$artifact" ]] || { echo "sign_local: not found: $artifact" >&2; exit 1; }
  "$COSIGN" sign-blob --yes --key "$KEYDIR/ephemeral.key" --signing-config "$KEYDIR/signing_config.json" \
    --bundle "$artifact.sigstore.json" "$artifact" >/dev/null 2>&1 \
    || { echo "sign_local: signing failed: $artifact" >&2; exit 1; }
  echo "signed  $artifact -> $artifact.sigstore.json"
done

mkdir -p "$(dirname "$PUB_OUT")"
cp "$KEYDIR/ephemeral.pub" "$PUB_OUT"
echo "public key $PUB_OUT (sha256 $(sha256sum "$PUB_OUT" | cut -d' ' -f1)); private key destroyed"
