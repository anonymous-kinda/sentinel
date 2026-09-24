"""deploy/tools.lock: every third-party binary and trust root, pinned by sha256.

Wrong input raises (a malformed pin, a digest mismatch, a name with no pin
for the requested architecture); nothing unverified is ever written.
"""

import hashlib
import pathlib

import pytest

from supplychain.toolslock import LockError, ToolPin, fetch, read_lock, select

HEX = "a" * 64


def lock_file(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    path = tmp_path / "tools.lock"
    path.write_text(body)
    return path


def pin(name: str, arch: str, url: str = "https://example.invalid/x", sha: str = HEX, member: str = "-") -> ToolPin:
    return ToolPin(name=name, version="1.0", arch=arch, sha256=sha, url=url, member=member)


def test_rows_parse_and_comments_and_blank_lines_are_ignored(tmp_path):
    path = lock_file(tmp_path, f"# header\n\ncosign 3.1.3 x86_64 {HEX} https://example.invalid/c -\n")
    assert read_lock(path) == [
        ToolPin(name="cosign", version="3.1.3", arch="x86_64", sha256=HEX, url="https://example.invalid/c", member="-")
    ]


def test_a_row_with_the_wrong_number_of_columns_raises(tmp_path):
    path = lock_file(tmp_path, f"cosign 3.1.3 x86_64 {HEX} https://example.invalid/c\n")
    with pytest.raises(LockError, match="line 1"):
        read_lock(path)


def test_a_digest_that_is_not_64_hex_characters_raises(tmp_path):
    path = lock_file(tmp_path, "cosign 3.1.3 x86_64 deadbeef https://example.invalid/c -\n")
    with pytest.raises(LockError, match="sha256"):
        read_lock(path)


def test_select_returns_the_arch_rows_plus_noarch_rows():
    pins = [pin("uv", "x86_64"), pin("uv", "aarch64"), pin("root.json", "noarch")]
    assert [(p.name, p.arch) for p in select(pins, "x86_64")] == [("uv", "x86_64"), ("root.json", "noarch")]


def test_select_filters_by_name():
    pins = [pin("uv", "x86_64"), pin("cosign", "x86_64")]
    assert [p.name for p in select(pins, "x86_64", ["cosign"])] == ["cosign"]


def test_select_raises_for_a_requested_name_with_no_pin_for_that_arch():
    pins = [pin("uv", "x86_64"), pin("cosign", "aarch64")]
    with pytest.raises(LockError, match="cosign"):
        select(pins, "x86_64", ["uv", "cosign"])


def served(tmp_path: pathlib.Path, payload: bytes) -> str:
    src = tmp_path / "served.bin"
    src.write_bytes(payload)
    return src.as_uri()  # file:// - no socket is opened


def test_fetch_writes_a_verified_executable(tmp_path):
    payload = b"#!/bin/sh\necho ok\n"
    p = pin("tool", "x86_64", served(tmp_path, payload), hashlib.sha256(payload).hexdigest())
    dest = fetch(p, tmp_path / "out")
    assert dest.read_bytes() == payload
    assert dest.stat().st_mode & 0o777 == 0o755


def test_fetch_writes_json_trust_material_without_the_execute_bit(tmp_path):
    payload = b'{"mediaType": "x"}'
    p = pin("trusted_root.json", "noarch", served(tmp_path, payload), hashlib.sha256(payload).hexdigest())
    dest = fetch(p, tmp_path / "out")
    assert dest.stat().st_mode & 0o777 == 0o644


def test_fetch_refuses_a_digest_mismatch_and_writes_nothing(tmp_path):
    p = pin("tool", "x86_64", served(tmp_path, b"tampered"), HEX)
    with pytest.raises(LockError, match="SHA-256 mismatch"):
        fetch(p, tmp_path / "out")
    assert not (tmp_path / "out" / "tool").exists()


def test_fetch_extracts_the_pinned_member_of_a_tarball(tmp_path):
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"binary"
        info = tarfile.TarInfo("dist/tool")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    blob = buf.getvalue()
    p = pin("tool", "x86_64", served(tmp_path, blob), hashlib.sha256(blob).hexdigest(), member="dist/tool")
    assert fetch(p, tmp_path / "out").read_bytes() == b"binary"


def test_fetch_skips_the_download_when_the_recorded_digest_matches(tmp_path):
    payload = b"v1"
    p = pin("tool", "x86_64", served(tmp_path, payload), hashlib.sha256(payload).hexdigest())
    dest = fetch(p, tmp_path / "out")
    (tmp_path / "served.bin").unlink()  # a second download would now fail
    assert fetch(p, tmp_path / "out") == dest


def test_the_committed_lock_parses_and_pins_both_architectures_for_every_tool():
    lock = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "tools.lock"
    pins = read_lock(lock)
    by_name: dict[str, set[str]] = {}
    for p in pins:
        by_name.setdefault(p.name, set()).add(p.arch)
    per_arch = {name: arches for name, arches in by_name.items() if arches != {"noarch"}}
    assert all(arches == {"x86_64", "aarch64"} for arches in per_arch.values()), per_arch
    assert {"cosign", "syft", "trivy", "hadolint", "actionlint", "shellcheck", "crane"} <= set(per_arch)
    assert by_name.get("sigstore-trusted-root.json") == {"noarch"}


@pytest.mark.parametrize("member", ["-", "dist/tool"])
def test_a_reused_tool_is_the_verified_one_not_whatever_is_on_disk(tmp_path, member):
    """The skip-if-present path trusted its stamp, not the file: a binary
    changed after download was reused (and shipped in the bundle, whose
    manifest still quoted the pinned digest)."""
    import io
    import tarfile

    data = b"genuine binary"
    blob = data
    if member != "-":
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        blob = buf.getvalue()
    p = pin("tool", "x86_64", served(tmp_path, blob), hashlib.sha256(blob).hexdigest(), member=member)
    dest = fetch(p, tmp_path / "out")
    dest.write_bytes(b"swapped after download")

    assert fetch(p, tmp_path / "out").read_bytes() == data
