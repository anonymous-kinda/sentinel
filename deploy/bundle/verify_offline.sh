#!/usr/bin/env bash
# Prove a bundle installs and runs with no network at all.
#
#   deploy/bundle/verify_offline.sh dist/sentinel-<ver>-<arch>.tar.gz
#
# Runs inside `unshare -rn`: a user + network namespace whose only interface
# is loopback, so any attempt to reach a package index, CDN or tile server
# fails the run. Checks: integrity manifest, offline dependency install,
# node health, NASA validation reproduced, console and Cesium assets served.
set -euo pipefail
BUNDLE=$(realpath "$1")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
tar -xzf "$BUNDLE" -C "$WORK"
DIR=$(find "$WORK" -maxdepth 1 -mindepth 1 -type d | head -1)

unshare -rn bash -euo pipefail -c '
  ip link set lo up 2>/dev/null || true
  if curl -s -m 3 https://pypi.org >/dev/null 2>&1; then echo "FAIL: namespace has network"; exit 1; fi
  cd "'"$DIR"'"
  PREFIX="'"$WORK"'/opt" SYSTEMD=0 ./install.sh
  cd "'"$WORK"'/opt"
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
echo "PASS: $(basename "$BUNDLE") installs and runs with no network"
