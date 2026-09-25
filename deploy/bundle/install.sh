#!/usr/bin/env bash
# Sentinel offline installer.
#
#   sudo ./install.sh                       # install to /opt/sentinel, enable systemd units
#   PREFIX=$HOME/sentinel SYSTEMD=0 ./install.sh   # unprivileged install, no services
#
# Requirements on the host: Linux (glibc), python3.12, and systemd if SYSTEMD=1.
# Nothing is downloaded. Every file is checked against SHA256SUMS first, and
# every dependency is installed from wheels/ with --no-index --require-hashes.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
PREFIX=${PREFIX:-/opt/sentinel}
SYSTEMD=${SYSTEMD:-1}
ROLE=${SENTINEL_ROLE:-standalone}
cd "$HERE"

echo "==> verifying bundle integrity (SHA256SUMS)"
sha256sum --quiet --strict -c SHA256SUMS
# sha256sum checks only the files the list names. Everything below is
# installed by directory or by glob, so a file added after signing would
# ride along unverified: refuse anything in those paths the list does not name.
unlisted=$(LC_ALL=C comm -23 \
  <(find web fixtures bin wheels systemd ! -type d 2>/dev/null | LC_ALL=C sort) \
  <(sed -E 's/^[0-9a-f]{64}  //' SHA256SUMS | LC_ALL=C sort))
if [[ -n "$unlisted" ]]; then
  echo "install: refusing files that SHA256SUMS does not list:" >&2
  echo "$unlisted" >&2
  exit 1
fi

PY=${PYTHON:-$(command -v python3.12 || true)}
if [[ -z "$PY" ]]; then
  echo "python3.12 is required on the host" >&2
  exit 1
fi

export UV_OFFLINE=1 UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never
echo "==> creating virtual environment in $PREFIX/venv"
mkdir -p "$PREFIX"
./bin/uv venv --quiet --allow-existing --python "$PY" "$PREFIX/venv"

echo "==> installing hash-pinned dependencies (offline)"
./bin/uv pip install --quiet --python "$PREFIX/venv/bin/python" \
  --no-index --find-links wheels --require-hashes -r requirements.txt
./bin/uv pip install --quiet --python "$PREFIX/venv/bin/python" \
  --no-index --no-deps --reinstall-package sentinel wheels/sentinel-*.whl

echo "==> installing console, reference data and binaries"
rm -rf "${PREFIX:?}/web" "${PREFIX:?}/fixtures" "${PREFIX:?}/bin"
cp -r web fixtures bin "$PREFIX/"
cp VERSION SHA256SUMS "$PREFIX/"
mkdir -p "$PREFIX/var"

if [[ ! -f "$PREFIX/sentinel.env" ]]; then
  cat > "$PREFIX/sentinel.env" <<ENV
SENTINEL_NODE_ID=$(hostname -s)
SENTINEL_ROLE=$ROLE
SENTINEL_DB=$PREFIX/var/sentinel.db
SENTINEL_VAR=$PREFIX/var
SENTINEL_WEB_DIST=$PREFIX/web
SENTINEL_FIXTURES=$PREFIX/fixtures
SENTINEL_MARKING="UNCLASSIFIED // EXERCISE"
SENTINEL_EXERCISE=1
SENTINEL_LIBRARY=1
SENTINEL_READ_ONLY=0
ENV
fi

if [[ "$SYSTEMD" == "1" ]]; then
  echo "==> installing systemd units"
  id sentinel >/dev/null 2>&1 || useradd --system --home-dir "$PREFIX" --shell /usr/sbin/nologin sentinel
  chown -R sentinel:sentinel "$PREFIX/var"
  sed "s#@PREFIX@#$PREFIX#g" systemd/sentinel.service > /etc/systemd/system/sentinel.service
  systemctl daemon-reload
  systemctl enable --now sentinel.service
  echo "==> sentinel.service is $(systemctl is-active sentinel.service)"
fi

echo "==> installed $(head -1 VERSION) to $PREFIX"
