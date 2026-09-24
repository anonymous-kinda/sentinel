#!/usr/bin/env python3
"""Write SBOMs for what ships: the Python runtime and the web console.

    uv run python scripts/sbom.py [--out dist/sbom]

    dist/sbom/sentinel-python-runtime.spdx.json   dist/sbom/sentinel-python-runtime.cdx.json
    dist/sbom/sentinel-web-console.spdx.json      dist/sbom/sentinel-web-console.cdx.json

Python runtime: the hash-locked runtime set (uv export, no dev or optional
extras) plus the sentinel wheel, installed into a staging directory for
CPython 3.12 on manylinux - the bundle's target - and catalogued from the
installed metadata, so environment markers are resolved exactly as they are
in the bundle. Component versions are identical for x86_64 and aarch64 (and
for the container's CPython 3.14); per-file wheel digests differ by arch
and are in each bundle's BUNDLE.json and SHA256SUMS.

Web console: the production dependency closure of web/package-lock.json
(syft excludes devDependencies), i.e. what Vite bundles into web/dist.

An SBOM with no components, or without a component known to ship, is a
wrong answer and fails the run. Needs network (uv fetches wheels).
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel.obs import configure_logging, get_logger  # noqa: I001
from supplychain.bundle import PYTHON_TAG, export_requirements
from supplychain.sbom import SbomError, require_components, syft_command

log = get_logger("scripts.sbom")
HOST_ARCH = {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine(), platform.machine())
FORMATS = {"spdx-json": "spdx.json", "cyclonedx-json": "cdx.json"}
SUBJECTS = {
    "sentinel-python-runtime": {"sentinel", "numpy", "scipy", "fastapi", "cryptography", "skyfield"},
    "sentinel-web-console": {"react", "react-dom", "cesium"},
}


def run(*cmd: str, cwd: pathlib.Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, env={**os.environ, "SYFT_CHECK_FOR_APP_UPDATE": "false"})


def stage_python(stage: pathlib.Path) -> pathlib.Path:
    target = stage / "sentinel-python-runtime"
    requirements = stage / "requirements.txt"
    requirements.write_text(export_requirements(ROOT))
    wheel_dir = stage / "wheel"
    run("uv", "build", "--quiet", "--wheel", "--out-dir", str(wheel_dir), cwd=ROOT)
    common = ["--quiet", "--target", str(target), "--python-version", PYTHON_TAG,
              "--python-platform", f"{HOST_ARCH}-manylinux_2_28", "--no-deps"]
    run("uv", "pip", "install", *common, "--require-hashes", "-r", str(requirements))
    run("uv", "pip", "install", *common, *map(str, wheel_dir.glob("sentinel-*.whl")))
    return target


def stage_web(stage: pathlib.Path) -> pathlib.Path:
    target = stage / "sentinel-web-console"
    target.mkdir()
    for name in ("package.json", "package-lock.json"):
        shutil.copy2(ROOT / "web" / name, target / name)
    return target


def write_sboms(subject: str, source: pathlib.Path, out: pathlib.Path, version: str) -> None:
    syft = str(ROOT / ".tools" / HOST_ARCH / "syft")
    outputs = {fmt: str(out / f"{subject}.{ext}") for fmt, ext in FORMATS.items()}
    run(*syft_command(syft, str(source), name=subject, version=version, outputs=outputs))
    for path in outputs.values():
        count = require_components(json.loads(pathlib.Path(path).read_text()), SUBJECTS[subject], subject)
        log.info("SBOM written", subject=subject, path=str(pathlib.Path(path).relative_to(ROOT)), components=count)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "dist" / "sbom")
    args = parser.parse_args()
    configure_logging()
    from sentinel import __version__

    out = args.out.resolve()
    stage = out / ".stage"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    try:
        write_sboms("sentinel-python-runtime", stage_python(stage), out, __version__)
        write_sboms("sentinel-web-console", stage_web(stage), out, __version__)
    except SbomError as error:
        log.error("SBOM incomplete", error=str(error))
        sys.exit(1)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    main()
