"""The air-gap bundle's reproducible tarball and its machine-readable manifest.

The manifest (BUNDLE.json inside the tarball) is the component inventory a
receiving site can read without unpacking wheels: what was built, from which
commit, which pinned third-party binaries it carries (with upstream URL and
digest), and the digest of every wheel (CM-8, SR-4).
"""

from __future__ import annotations

import gzip
import pathlib
import subprocess
import tarfile
from collections.abc import Iterable, Sequence

from .checksums import sha256_file
from .toolslock import ToolPin, select

MANIFEST_FORMAT = 1
PYTHON_TAG = "3.12"


def export_requirements(root: pathlib.Path) -> str:
    """The runtime dependency set, hash-locked from uv.lock: what the bundle,
    the container and the Python SBOM all install. No dev or optional extras."""
    return subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt"],
        cwd=root, check=True, text=True, capture_output=True,
    ).stdout


def write_tarball(stage: pathlib.Path, tarball: pathlib.Path, prefix: str, epoch: int) -> pathlib.Path:
    """Sorted entries, root ownership, normalised modes, every timestamp = epoch.

    The gzip header's own timestamp is the epoch too and carries no file
    name, so the same tree gives the same bytes on the same toolchain.
    """

    def normalise(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        info.mtime = epoch
        info.mode = 0o755 if info.isdir() or info.mode & 0o111 else 0o644
        return info

    with (
        tarball.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9) as gz,
        tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar,
    ):
        for path in sorted(stage.rglob("*")):
            arcname = f"{prefix}/{path.relative_to(stage).as_posix()}"
            tar.add(path, arcname=arcname, recursive=False, filter=normalise)
    return tarball


def bundle_manifest(
    stage: pathlib.Path,
    *,
    version: str,
    arch: str,
    python: str,
    commit: str,
    source_date_epoch: int,
    pins: Iterable[ToolPin],
    shipped_tools: Sequence[str],
) -> dict:
    tools = sorted(select(pins, arch, shipped_tools), key=lambda p: p.name)
    wheels = sorted((stage / "wheels").glob("*.whl"))
    return {
        "format": MANIFEST_FORMAT,
        "bundle": {
            "name": "sentinel",
            "version": version,
            "arch": arch,
            "python": python,
            "commit": commit,
            "source_date_epoch": source_date_epoch,
        },
        "tools": [
            {"name": p.name, "version": p.version, "sha256": p.sha256, "url": p.url, "lock": "deploy/tools.lock"}
            for p in tools
        ],
        "wheels": [{"file": w.name, "sha256": sha256_file(w)} for w in wheels],
    }
