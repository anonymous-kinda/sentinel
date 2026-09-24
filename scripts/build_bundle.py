#!/usr/bin/env python3
"""Build an installable Sentinel bundle for one or more CPU architectures.

    uv run python scripts/build_bundle.py --arch aarch64
    uv run python scripts/build_bundle.py --arch x86_64 --arch aarch64

Output: dist/sentinel-<version>-<arch>.tar.gz (+ .sha256), containing

    wheels/            sentinel + every dependency, pinned by hash
    requirements.txt   the hash-locked dependency set (uv export)
    bin/               uv and nats-server for the target arch (tools.lock)
    web/               the built console (Cesium assets included)
    fixtures/          NASA CARA reference data (NOSA 1.3, unmodified)
    systemd/           hardened unit files
    install.sh         offline installer
    VERSION            human-readable identity
    BUNDLE.json        machine-readable manifest: commit, pinned tools, wheel digests
    SHA256SUMS         per-file integrity manifest, written last

The same bundle installs the AWS hub, an edge laptop, and a disconnected
enclave. Installing never touches the network: dependencies come from
wheels/ with --no-index and --require-hashes. The tarball is reproducible:
SOURCE_DATE_EPOCH (default: the commit time) fixes every timestamp. Its
signature travels beside it (<tarball>.sigstore.json, docs/supply-chain.md).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from supplychain.bundle import PYTHON_TAG, bundle_manifest, export_requirements, write_tarball  # noqa: I001
from supplychain.checksums import sha256_file, write_manifest
from supplychain.toolslock import read_lock

SHIPPED_TOOLS = ("uv", "nats-server")
PLATFORMS = {
    "x86_64": ["manylinux_2_28_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64"],
    "aarch64": ["manylinux_2_28_aarch64", "manylinux_2_17_aarch64", "manylinux2014_aarch64"],
}


def run(*cmd: str, cwd: pathlib.Path | None = None, capture: bool = False) -> str:
    print("+", " ".join(cmd))
    result = subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=capture)
    return result.stdout if capture else ""


def version() -> str:
    from sentinel import __version__

    return __version__


def source_date_epoch() -> int:
    """SOURCE_DATE_EPOCH if set, else the commit time: reproducible by default."""
    explicit = os.environ.get("SOURCE_DATE_EPOCH")
    if explicit:
        return int(explicit)
    return int(run("git", "log", "-1", "--format=%ct", cwd=ROOT, capture=True).strip())


def build(arch: str, out_dir: pathlib.Path) -> pathlib.Path:
    ver = version()
    epoch = source_date_epoch()
    os.environ["SOURCE_DATE_EPOCH"] = str(epoch)  # the wheel build stamps its zip entries with it
    name = f"sentinel-{ver}-{arch}"
    stage = out_dir / name
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "wheels").mkdir(parents=True)

    web_dist = ROOT / "web" / "dist"
    if not (web_dist / "index.html").exists():
        sys.exit("web/dist is missing: run `make web` first")

    # 1. The project wheel.
    run("uv", "build", "--wheel", "--out-dir", str(stage / "wheels"), cwd=ROOT)

    # 2. The dependency set, locked with hashes.
    (stage / "requirements.txt").write_text(export_requirements(ROOT))

    # 3. Dependency wheels for the target platform, verified against those hashes.
    platform_args = [arg for p in PLATFORMS[arch] for arg in ("--platform", p)]
    run(
        "uvx", "pip", "download", "--quiet", "--require-hashes", "-r", str(stage / "requirements.txt"),
        "--only-binary=:all:", *platform_args, "--python-version", PYTHON_TAG,
        "--implementation", "cp", "--abi", f"cp{PYTHON_TAG.replace('.', '')}",
        "-d", str(stage / "wheels"),
    )

    # 4. Pinned binaries for the target architecture.
    run(sys.executable, str(ROOT / "scripts" / "fetch_tools.py"), "--arch", arch, *SHIPPED_TOOLS)
    (stage / "bin").mkdir()
    for tool in SHIPPED_TOOLS:
        shutil.copy2(ROOT / ".tools" / arch / tool, stage / "bin" / tool)

    # 5. Console, reference data, deployment files.
    shutil.copytree(web_dist, stage / "web")
    (stage / "fixtures").mkdir()
    shutil.copytree(ROOT / "fixtures" / "cara", stage / "fixtures" / "cara")
    shutil.copy2(ROOT / "fixtures" / "cara_cases.json", stage / "fixtures" / "cara_cases.json")
    shutil.copytree(ROOT / "deploy" / "systemd", stage / "systemd")
    shutil.copy2(ROOT / "deploy" / "bundle" / "install.sh", stage / "install.sh")
    shutil.copy2(ROOT / "LICENSE", stage / "LICENSE")
    commit = run("git", "rev-parse", "HEAD", cwd=ROOT, capture=True).strip()
    dirty = bool(run("git", "status", "--porcelain", "--untracked-files=no", cwd=ROOT, capture=True).strip())
    tree = "dirty" if dirty else "clean"
    (stage / "VERSION").write_text(f"sentinel {ver}\ncommit {commit[:12]} ({tree})\narch {arch}\npython {PYTHON_TAG}\n")

    # 6. Machine-readable manifest, then the integrity manifest over everything, written last.
    manifest = bundle_manifest(
        stage, version=ver, arch=arch, python=PYTHON_TAG, commit=commit, source_date_epoch=epoch,
        pins=read_lock(ROOT / "deploy" / "tools.lock"), shipped_tools=SHIPPED_TOOLS, dirty=dirty,
    )
    (stage / "BUNDLE.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    write_manifest(stage)

    # 7. Reproducible tarball: sorted entries, fixed ownership, modes and timestamps.
    tarball = write_tarball(stage, out_dir / f"{name}.tar.gz", name, epoch)
    (out_dir / f"{name}.tar.gz.sha256").write_text(f"{sha256_file(tarball)}  {tarball.name}\n")
    shutil.rmtree(stage)
    print(f"bundle: {tarball} ({tarball.stat().st_size / 1e6:.1f} MB, SOURCE_DATE_EPOCH={epoch})")
    return tarball


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", choices=sorted(PLATFORMS), action="append",
                        help="repeat for several architectures (default: x86_64)")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for arch in args.arch or ["x86_64"]:
        build(arch, out)


if __name__ == "__main__":
    main()
