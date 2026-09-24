#!/usr/bin/env bash
# Prove a signed bundle verifies, installs and runs with no network at all.
#
#   SENTINEL_VERIFY_KEY=dist/local-signing-key.pub \
#     deploy/bundle/verify_offline.sh dist/sentinel-<ver>-<arch>.tar.gz          # local proof
#   SENTINEL_TRUSTED_ROOT=trusted_root.json SENTINEL_CERT_IDENTITY=https://github.com/... \
#     deploy/bundle/verify_offline.sh sentinel-<ver>-<arch>.tar.gz                # release
#
# The verification policy is verify_signature.sh's (see there). Everything
# runs inside `unshare -rn`: a user + network namespace whose only interface
# is loopback, so any attempt to reach Sigstore, a package index, a CDN or a
# tile server fails the run. Order, each step failing closed:
#   1. signature (cosign, offline)        SI-7, CM-14 - nothing is unpacked before this
#   2. tarball digest (.sha256, if present)
#   3. per-file SHA256SUMS and --require-hashes install (install.sh)
#   4. node health, NASA validation reproduced, console and Cesium assets served
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BUNDLE=$(realpath "$1")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export BUNDLE WORK VERIFY="$HERE/verify_signature.sh" COSIGN=${COSIGN:-cosign}

# shellcheck disable=SC2016  # single quotes on purpose: the inner shell expands the exported variables
unshare -rn bash -euo pipefail -c '
  ip link set lo up 2>/dev/null || true
  if curl -s -m 3 https://pypi.org >/dev/null 2>&1; then echo "FAIL: namespace has network"; exit 1; fi
  bash "$VERIFY" "$BUNDLE" || { echo "FAIL: signature verification - bundle not unpacked"; exit 1; }
  if [[ -f "$BUNDLE.sha256" ]]; then
    (cd "$(dirname "$BUNDLE")" && sha256sum --quiet --strict -c "$(basename "$BUNDLE").sha256") \
      || { echo "FAIL: tarball digest"; exit 1; }
  fi
  tar -xzf "$BUNDLE" -C "$WORK"
  DIR=$(find "$WORK" -maxdepth 1 -mindepth 1 -type d | head -1)
  cd "$DIR"
  PREFIX="$WORK/opt" SYSTEMD=0 ./install.sh
  cd "$WORK/opt"
  set -a; . ./sentinel.env; set +a
  SENTINEL_DB=:memory: ./venv/bin/sentinel serve --port 18799 > serve.log 2>&1 &
  for _ in $(seq 1 60); do curl -sf -m 1 http://127.0.0.1:18799/api/health >/dev/null && break; sleep 0.5; done
  curl -sf http://127.0.0.1:18799/api/health >/dev/null || { cat serve.log; echo "FAIL: node did not start"; exit 1; }
  curl -sf http://127.0.0.1:18799/api/validation | ./venv/bin/python -c "
import json, sys
d = json.load(sys.stdin)
assert d[\"available\"] and d[\"operational_count\"] == 53, d
assert d[\"worst_rel_error\"] < 1e-6 and d[\"confusion\"][\"fn\"] == 0, d
print(f\"  validation reproduced offline: 53 events, worst rel error {d[\"worst_rel_error\"]:.1e}, false negatives 0\")"
  curl -sf -o /dev/null http://127.0.0.1:18799/ || { echo "FAIL: console"; exit 1; }
  curl -sf -o /dev/null http://127.0.0.1:18799/cesium/Assets/Textures/NaturalEarthII/tilemapresource.xml || { echo "FAIL: cesium assets"; exit 1; }
  echo "  console and offline globe imagery served"
  kill %1
'
echo "PASS: $(basename "$BUNDLE") is authentic, installs and runs with no network"
