#!/usr/bin/env bash
# Prove the Ansible role refuses to go past its signature gate unless the
# bundle verifies (SI-7, CM-14). Runs the role's verify tasks against
# localhost with a locally signed fixture bundle:
#   good signature           -> passes
#   tampered bundle          -> refused (even with a regenerated .sha256)
#   no signature policy      -> refused before anything is copied
#
#   deploy/ansible/tests/test_verify.sh      (needs uvx; it fetches ansible-core at the
#                                            version ci.yml's syntax check pins)
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../../.." && pwd)
ARCH=$(uname -m); ARCH=${ARCH/arm64/aarch64}; ARCH=${ARCH/amd64/x86_64}
COSIGN=$REPO/.tools/$ARCH/cosign
[[ -x "$COSIGN" ]] || { echo "test_verify: missing $COSIGN - run make supply-tools" >&2; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
NAME=sentinel-0.0.0-$ARCH
mkdir -p "$WORK/dist" "$WORK/src/$NAME"
echo "fixture" > "$WORK/src/$NAME/VERSION"
tar -czf "$WORK/dist/$NAME.tar.gz" -C "$WORK/src" "$NAME"
(cd "$WORK/dist" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
COSIGN=$COSIGN bash "$REPO/deploy/bundle/sign_local.sh" --pubkey-out "$WORK/site.pub" "$WORK/dist/$NAME.tar.gz" >/dev/null

playbook() {  # playbook <extra -e args...>
  (cd "$WORK" && ANSIBLE_ROLES_PATH="$REPO/deploy/ansible/roles" ANSIBLE_NOCOLOR=1 \
    uvx --quiet --from ansible-core==2.21.4 ansible-playbook -i localhost, "$REPO/deploy/ansible/tests/verify.yml" \
      -e ansible_python_interpreter="$(command -v python3)" \
      -e sentinel_repo_root="$REPO" -e sentinel_bundle_dir="$WORK/dist" \
      -e sentinel_stage_dir="$WORK/stage" -e sentinel_arch="$ARCH" -e sentinel_version=0.0.0 \
      "$@" 2>&1)
}

failures=0
check() {  # check pass|fail "<label>" "<text expected in output on fail>" <-e args...>
  local want=$1 label=$2 needle=$3; shift 3
  local out rc=0
  mkdir -p "$WORK/stage"
  out=$(playbook "$@") || rc=$?
  if [[ $want == pass && $rc -eq 0 ]] || [[ $want == fail && $rc -ne 0 && $out == *"$needle"* ]]; then
    echo "  ok    $label"
  else
    echo "  WRONG $label (exit $rc)"; echo "$out" | tail -25 | sed 's/^/        /'; failures=$((failures + 1))
  fi
  rm -rf "$WORK/stage"
}

KEY=(-e sentinel_verify_mode=key -e sentinel_verify_key="$WORK/site.pub")
check pass "good signature passes the gate" "" "${KEY[@]}"

cp "$WORK/dist/$NAME.tar.gz" "$WORK/good.tar.gz"
printf 'x' >> "$WORK/dist/$NAME.tar.gz"
(cd "$WORK/dist" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")   # attacker fixes the digest too
check fail "tampered bundle is refused" "FAIL: signature" "${KEY[@]}"
cp "$WORK/good.tar.gz" "$WORK/dist/$NAME.tar.gz"

check fail "no signature policy is refused" "No usable signature policy" -e sentinel_verify_mode=keyless -e sentinel_repository=

# Keyless branch, for real: cosign's own release binary and its Sigstore bundle
# stand in for a release tarball (the signature covers bytes, not the name),
# verified against the pinned trusted root with the Sigstore project's identity.
KEYLESS_NAME=sentinel-0.0.1-$ARCH
cp "$COSIGN" "$WORK/dist/$KEYLESS_NAME.tar.gz"
cp "$COSIGN.sigstore.json" "$WORK/dist/$KEYLESS_NAME.tar.gz.sigstore.json"
(cd "$WORK/dist" && sha256sum "$KEYLESS_NAME.tar.gz" > "$KEYLESS_NAME.tar.gz.sha256")
KEYLESS=(-e sentinel_version=0.0.1 -e sentinel_verify_mode=keyless -e sentinel_repository=unused
         -e sentinel_signer_issuer=https://accounts.google.com)
check pass "keyless signature verifies against the pinned trusted root" "" "${KEYLESS[@]}" \
  -e sentinel_signer_identity=keyless@projectsigstore.iam.gserviceaccount.com
check fail "keyless signature from another identity is refused" "FAIL: signature" "${KEYLESS[@]}" \
  -e sentinel_signer_identity=https://github.com/attacker/sentinel/.github/workflows/release.yml@refs/tags/v0.0.1

if (( failures )); then echo "test_verify: FAIL ($failures)" >&2; exit 1; fi
echo "PASS: the sentinel role verifies the signature before anything is unpacked"
