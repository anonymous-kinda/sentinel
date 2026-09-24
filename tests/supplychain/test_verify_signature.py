"""deploy/bundle/verify_signature.sh: the one verification policy (SI-7, CM-14, SR-11).

Used by `make airgap-verify`, by verify_offline.sh inside `unshare -rn`, and
by the Ansible role on the target host before anything is unpacked. These
tests pin its policy logic with a stub cosign that records its argv; the
real cosign is exercised end to end by `make airgap-selftest`.
"""

import hashlib
import pathlib
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "bundle" / "verify_signature.sh"
IDENTITY = "https://github.com/example/sentinel/.github/workflows/release.yml@refs/tags/v0.2.0"
STUB = """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$STUB_ARGV"
exit "${STUB_EXIT:-0}"
"""


@pytest.fixture
def env(tmp_path):
    cosign = tmp_path / "cosign"
    cosign.write_text(STUB)
    cosign.chmod(0o755)
    artifact = tmp_path / "sentinel-0.2.0-x86_64.tar.gz"
    artifact.write_bytes(b"bundle")
    (tmp_path / "sentinel-0.2.0-x86_64.tar.gz.sigstore.json").write_text("{}")
    (tmp_path / "trusted_root.json").write_text('{"mediaType": "trustedroot"}')
    (tmp_path / "site.pub").write_text("-----BEGIN PUBLIC KEY-----\n")
    return {
        "PATH": "/usr/bin:/bin",
        "COSIGN": str(cosign),
        "STUB_ARGV": str(tmp_path / "argv"),
        "_artifact": str(artifact),
        "_dir": str(tmp_path),
    }


def run(env: dict, **overrides: str) -> subprocess.CompletedProcess:
    merged = {k: v for k, v in {**env, **overrides}.items() if not k.startswith("_")}
    return subprocess.run(["bash", str(SCRIPT), env["_artifact"]], env=merged, capture_output=True, text=True)


def argv(env: dict) -> list[str] | None:
    path = pathlib.Path(env["STUB_ARGV"])
    return path.read_text().splitlines() if path.exists() else None


def keyless(env: dict) -> dict:
    return {"SENTINEL_TRUSTED_ROOT": f"{env['_dir']}/trusted_root.json", "SENTINEL_CERT_IDENTITY": IDENTITY}


def test_keyless_verifies_against_the_bundle_trust_root_identity_and_issuer(env):
    result = run(env, **keyless(env))
    assert result.returncode == 0, result.stderr
    assert argv(env) == [
        "verify-blob",
        "--bundle", f"{env['_artifact']}.sigstore.json",
        "--trusted-root", f"{env['_dir']}/trusted_root.json",
        "--certificate-identity", IDENTITY,
        "--certificate-oidc-issuer", "https://token.actions.githubusercontent.com",
        env["_artifact"],
    ]
    assert "OK" in result.stdout


def test_keyless_never_skips_the_transparency_log(env):
    run(env, **keyless(env))
    assert "--insecure-ignore-tlog" not in argv(env)


def test_key_mode_uses_the_public_key_and_says_the_tlog_is_absent(env):
    result = run(env, SENTINEL_VERIFY_KEY=f"{env['_dir']}/site.pub")
    assert result.returncode == 0, result.stderr
    assert argv(env) == [
        "verify-blob", "--bundle", f"{env['_artifact']}.sigstore.json",
        "--key", f"{env['_dir']}/site.pub", "--insecure-ignore-tlog", env["_artifact"],
    ]
    assert "no transparency log" in result.stderr


def test_a_rejected_signature_fails_closed(env):
    result = run(env, STUB_EXIT="1", **keyless(env))
    assert result.returncode != 0
    assert "FAIL: signature" in result.stderr


def test_no_policy_is_refused_before_cosign_runs(env):
    result = run(env)
    assert result.returncode != 0
    assert "no verification policy" in result.stderr
    assert argv(env) is None


def test_two_policies_at_once_are_refused(env):
    result = run(env, SENTINEL_VERIFY_KEY=f"{env['_dir']}/site.pub", **keyless(env))
    assert result.returncode != 0
    assert "ambiguous" in result.stderr
    assert argv(env) is None


def test_keyless_without_an_identity_is_refused(env):
    result = run(env, SENTINEL_TRUSTED_ROOT=f"{env['_dir']}/trusted_root.json")
    assert result.returncode != 0
    assert "SENTINEL_CERT_IDENTITY" in result.stderr
    assert argv(env) is None


def test_a_missing_signature_bundle_is_refused(env):
    pathlib.Path(f"{env['_artifact']}.sigstore.json").unlink()
    result = run(env, **keyless(env))
    assert result.returncode != 0
    assert "no signature bundle" in result.stderr
    assert argv(env) is None


def test_a_missing_trusted_root_is_refused(env):
    result = run(env, SENTINEL_TRUSTED_ROOT=f"{env['_dir']}/nope.json", SENTINEL_CERT_IDENTITY=IDENTITY)
    assert result.returncode != 0
    assert "trusted root" in result.stderr
    assert argv(env) is None


def test_a_pinned_trusted_root_digest_is_checked_before_use(env):
    root = pathlib.Path(env["_dir"]) / "trusted_root.json"
    good = hashlib.sha256(root.read_bytes()).hexdigest()
    assert run(env, SENTINEL_TRUSTED_ROOT_SHA256=good, **keyless(env)).returncode == 0
    pathlib.Path(env["STUB_ARGV"]).unlink()
    result = run(env, SENTINEL_TRUSTED_ROOT_SHA256="0" * 64, **keyless(env))
    assert result.returncode != 0
    assert "trusted root digest" in result.stderr
    assert argv(env) is None


def test_a_missing_artifact_is_refused(env):
    pathlib.Path(env["_artifact"]).unlink()
    result = run(env, **keyless(env))
    assert result.returncode != 0
    assert argv(env) is None
