#!/usr/bin/env bash
# Check an unpacked bundle against its own SHA256SUMS: every listed file
# matches, and the bundle holds nothing the list does not name.
#
#   bash verify_contents.sh        (from anywhere: it checks the directory it sits in)
#
# install.sh and the release image (deploy/containers/Dockerfile) both run it
# before installing anything. sha256sum checks only the files the list names,
# and both install by directory and by glob, so a file added after signing
# would ride along unverified: anything the list does not name, anywhere in
# the bundle, is refused. The signature over the tarball, checked before
# unpacking (verify_signature.sh), is what makes the list itself trustworthy.
set -euo pipefail
cd "$(dirname "$0")"

sha256sum --quiet --strict -c SHA256SUMS
unlisted=$(LC_ALL=C comm -23 \
  <(find . ! -type d ! -path ./SHA256SUMS | sed 's#^\./##' | LC_ALL=C sort) \
  <(sed -E 's/^[0-9a-f]{64}  //' SHA256SUMS | LC_ALL=C sort))
if [[ -n "$unlisted" ]]; then
  echo "verify_contents: refusing files that SHA256SUMS does not list:" >&2
  echo "$unlisted" >&2
  exit 1
fi
