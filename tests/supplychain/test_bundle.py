"""The air-gap bundle: a reproducible tarball and a machine-readable manifest.

Reproducible means the same staged tree and SOURCE_DATE_EPOCH give the same
bytes, so a second party can rebuild and compare digests (SA-10, SR-4).
"""

import gzip
import hashlib
import io
import json
import os
import pathlib
import tarfile

from supplychain.bundle import bundle_manifest, write_tarball
from supplychain.toolslock import ToolPin

EPOCH = 1_760_000_000


def stage(root: pathlib.Path, mtime: int) -> pathlib.Path:
    (root / "wheels").mkdir(parents=True)
    (root / "wheels" / "numpy-2.5.3-cp312-cp312-manylinux_2_28_x86_64.whl").write_bytes(b"numpy")
    (root / "wheels" / "sentinel-0.2.0-py3-none-any.whl").write_bytes(b"sentinel")
    (root / "bin").mkdir()
    (root / "bin" / "uv").write_bytes(b"uv")
    (root / "bin" / "uv").chmod(0o755)
    for path in root.rglob("*"):
        os.utime(path, (mtime, mtime))
    return root


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_same_tree_and_epoch_give_identical_bytes_regardless_of_file_mtimes(tmp_path):
    a = write_tarball(stage(tmp_path / "a", mtime=1), tmp_path / "a.tar.gz", "sentinel-0.2.0-x86_64", EPOCH)
    b = write_tarball(stage(tmp_path / "b", mtime=999_999), tmp_path / "b.tar.gz", "sentinel-0.2.0-x86_64", EPOCH)
    assert digest(a) == digest(b)


def test_the_gzip_header_carries_the_epoch_not_the_build_time(tmp_path):
    out = write_tarball(stage(tmp_path / "s", mtime=1), tmp_path / "x.tar.gz", "p", EPOCH)
    header = out.read_bytes()[:10]
    assert int.from_bytes(header[4:8], "little") == EPOCH
    with gzip.open(out) as f:
        f.read()  # still a valid gzip stream


def test_entries_are_sorted_prefixed_root_owned_and_keep_the_execute_bit(tmp_path):
    out = write_tarball(stage(tmp_path / "s", mtime=1), tmp_path / "x.tar.gz", "sentinel-0.2.0-x86_64", EPOCH)
    with tarfile.open(out) as tar:
        members = tar.getmembers()
    names = [m.name for m in members]
    assert names == sorted(names)
    assert all(n.startswith("sentinel-0.2.0-x86_64/") for n in names)
    assert {(m.uid, m.gid, m.uname, m.gname) for m in members} == {(0, 0, "root", "root")}
    assert {m.mtime for m in members} == {EPOCH}
    uv = next(m for m in members if m.name.endswith("bin/uv"))
    assert uv.mode & 0o111


def pin(name: str, arch: str) -> ToolPin:
    return ToolPin(name, "1.0", arch, "b" * 64, f"https://example.invalid/{name}-{arch}", "-")


def test_manifest_records_identity_shipped_tools_for_this_arch_and_every_wheel(tmp_path):
    root = stage(tmp_path / "s", mtime=1)
    pins = [pin("uv", "x86_64"), pin("uv", "aarch64"), pin("nats-server", "x86_64"), pin("cosign", "x86_64")]
    doc = bundle_manifest(
        root, version="0.2.0", arch="x86_64", python="3.12", commit="abc123", source_date_epoch=EPOCH,
        pins=pins, shipped_tools=("uv", "nats-server"), dirty=False,
    )
    assert doc["bundle"] == {
        "name": "sentinel", "version": "0.2.0", "arch": "x86_64", "python": "3.12",
        "commit": "abc123", "source_tree": "clean", "source_date_epoch": EPOCH,
    }
    assert [(t["name"], t["url"]) for t in doc["tools"]] == [
        ("nats-server", "https://example.invalid/nats-server-x86_64"),
        ("uv", "https://example.invalid/uv-x86_64"),
    ]
    wheels = {w["file"]: w["sha256"] for w in doc["wheels"]}
    assert wheels["numpy-2.5.3-cp312-cp312-manylinux_2_28_x86_64.whl"] == hashlib.sha256(b"numpy").hexdigest()
    assert list(wheels) == sorted(wheels)


def test_manifest_refuses_a_shipped_tool_with_no_pin_for_the_arch(tmp_path):
    import pytest

    from supplychain.toolslock import LockError

    with pytest.raises(LockError, match="nats-server"):
        bundle_manifest(
            stage(tmp_path / "s", mtime=1), version="0.2.0", arch="aarch64", python="3.12", commit="c",
            source_date_epoch=EPOCH, pins=[pin("uv", "aarch64")], shipped_tools=("uv", "nats-server"), dirty=False,
        )


def test_manifest_serialises_deterministically(tmp_path):
    root = stage(tmp_path / "s", mtime=1)
    kwargs = dict(version="0.2.0", arch="x86_64", python="3.12", commit="c", source_date_epoch=EPOCH,
                  pins=[pin("uv", "x86_64")], shipped_tools=("uv",), dirty=False)
    first = json.dumps(bundle_manifest(root, **kwargs), sort_keys=True)
    assert first == json.dumps(bundle_manifest(root, **kwargs), sort_keys=True)
    assert io.StringIO(first).read()  # plain JSON, no custom types


def test_a_build_from_uncommitted_changes_says_so(tmp_path):
    # the commit id alone would claim the bundle is that commit; with local edits it is not
    doc = bundle_manifest(
        stage(tmp_path / "s", mtime=1), version="0.2.0", arch="x86_64", python="3.12", commit="abc123",
        source_date_epoch=EPOCH, pins=[pin("uv", "x86_64")], shipped_tools=("uv",), dirty=True,
    )
    assert doc["bundle"]["source_tree"] == "dirty"
