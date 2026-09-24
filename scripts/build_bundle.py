#!/usr/bin/env python3
"""Build an installable Sentinel bundle for one CPU architecture.

    uv run python scripts/build_bundle.py --arch aarch64

Output: dist/sentinel-<version>-<arch>.tar.gz (+ .sha256), containing

    wheels/            sentinel + every dependency, pinned by hash
    requirements.txt   the hash-locked dependency set (uv export)
    bin/               uv and nats-server for the target arch (tools.lock)
    web/               the built console (Cesium assets included)
    fixtures/          NASA CARA reference data (NOSA 1.3, unmodified)
    systemd/           hardened unit files
    install.sh         offline installer
    VERSION, SHA256SUMS

The same bundle installs the AWS hub, an edge laptop, and (M4) a
disconnected enclave. Installing never touches the network: dependencies
come from wheels/ with --no-index and --require-hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYTHON_TAG = "3.12"
PLATFORMS = {
    "x86_64": ["manylinux_2_28_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64"],
    "aarch64": ["manylinux_2_28_aarch64", "manylinux_2_17_aarch64", "manylinux2014_aarch64"],
}


def run(*cmd: str, cwd: pathlib.Path | None = None, capture: bool = False) -> str:
    print("+", " ".join(cmd))
    result = subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=capture)
    return result.stdout if capture else ""


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def version() -> str:
    sys.path.insert(0, str(ROOT))
    from sentinel import __version__

    return __version__


def build(arch: str, out_dir: pathlib.Path) -> pathlib.Path:
    ver = version()
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
    requirements = run(
        "uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt",
        cwd=ROOT, capture=True,
    )
    (stage / "requirements.txt").write_text(requirements)

    # 3. Dependency wheels for the target platform, verified against those hashes.
    platform_args = [arg for p in PLATFORMS[arch] for arg in ("--platform", p)]
    run(
        "uvx", "pip", "download", "--quiet", "--require-hashes", "-r", str(stage / "requirements.txt"),
        "--only-binary=:all:", *platform_args, "--python-version", PYTHON_TAG,
        "--implementation", "cp", "--abi", f"cp{PYTHON_TAG.replace('.', '')}",
        "-d", str(stage / "wheels"),
    )

    # 4. Pinned binaries for the target architecture.
    run(sys.executable, str(ROOT / "scripts" / "fetch_tools.py"), "--arch", arch, "uv", "nats-server")
    (stage / "bin").mkdir()
    for tool in ("uv", "nats-server"):
        shutil.copy2(ROOT / ".tools" / arch / tool, stage / "bin" / tool)

    # 5. Console, reference data, deployment files.
    shutil.copytree(web_dist, stage / "web")
    (stage / "fixtures").mkdir()
    shutil.copytree(ROOT / "fixtures" / "cara", stage / "fixtures" / "cara")
    shutil.copy2(ROOT / "fixtures" / "cara_cases.json", stage / "fixtures" / "cara_cases.json")
    shutil.copytree(ROOT / "deploy" / "systemd", stage / "systemd")
    shutil.copy2(ROOT / "deploy" / "bundle" / "install.sh", stage / "install.sh")
    shutil.copy2(ROOT / "LICENSE", stage / "LICENSE")
    commit = run("git", "rev-parse", "--short=12", "HEAD", cwd=ROOT, capture=True).strip()
    (stage / "VERSION").write_text(f"sentinel {ver}\ncommit {commit}\narch {arch}\npython {PYTHON_TAG}\n")

    # 6. Integrity manifest over everything, written last.
    lines = []
    for path in sorted(p for p in stage.rglob("*") if p.is_file()):
        rel = path.relative_to(stage).as_posix()
        lines.append(f"{sha256(path)}  {rel}")
    (stage / "SHA256SUMS").write_text("\n".join(lines) + "\n")

    # 7. Reproducible-ish tarball: sorted entries, fixed ownership and mtime.
    tarball = out_dir / f"{name}.tar.gz"
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0")) or None

    def normalise(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        if epoch is not None:
            info.mtime = epoch
        return info

    with tarfile.open(tarball, "w:gz") as tar:
        for path in sorted(stage.rglob("*")):
            tar.add(path, arcname=f"{name}/{path.relative_to(stage).as_posix()}", recursive=False, filter=normalise)
    (out_dir / f"{name}.tar.gz.sha256").write_text(f"{sha256(tarball)}  {tarball.name}\n")
    shutil.rmtree(stage)
    print(f"bundle: {tarball} ({tarball.stat().st_size / 1e6:.1f} MB)")
    return tarball


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", choices=sorted(PLATFORMS), default="x86_64")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    build(args.arch, out)


if __name__ == "__main__":
    main()
