#!/usr/bin/env python3
"""Vulnerability scan of what ships, with reviewed VEX applied (RA-5).

    uv run python scripts/scan.py              # scan, check VEX, gate  (make scan)
    uv run python scripts/scan.py --write-vex  # scan, rewrite the VEX document (make vex)

Two targets:
  source    `trivy fs .`     - uv.lock and web/package-lock.json (runtime deps;
                               Trivy skips npm devDependencies)
  binaries  `trivy rootfs`   - the nats-server and uv binaries the bundle carries,
                               both architectures, exactly as pinned in tools.lock

Order: (1) raw JSON scans, nothing suppressed; (2) every VEX statement must
answer a raw finding and its evidence must hold (supplychain.vex); (3) SARIF
scans with the VEX document applied, failing on any finding left, at any
severity. Outputs in dist/scan/. The vulnerability database is Trivy's
current one (not pinned): the same commit can pass today and fail tomorrow,
which is the point of RA-5.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import platform
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel.obs import configure_logging, get_logger  # noqa: I001
from supplychain import vex
from supplychain.toolslock import fetch, read_lock, select
from supplychain.trivy import FINDINGS_EXIT, trivy_command

log = get_logger("scripts.scan")
HOST_ARCH = {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine(), platform.machine())
TOOLS = ROOT / ".tools"
SHIPPED_BINARIES = ("uv", "nats-server")
ARCHES = ("x86_64", "aarch64")
SKIP_DIRS = (".venv", ".tools", ".claude", "dist", "web/node_modules", "web/dist", "harness/results")
STATEMENTS = ROOT / "deploy" / "vex" / "statements.toml"
VEX_DOC = ROOT / "deploy" / "vex" / "sentinel.openvex.json"


def stage_binaries(out: pathlib.Path) -> pathlib.Path:
    """The shipped binaries only, for both arches (hard links, no copies)."""
    pins = read_lock(ROOT / "deploy" / "tools.lock")
    stage = out / "bin"
    shutil.rmtree(stage, ignore_errors=True)
    for arch in ARCHES:
        (stage / arch).mkdir(parents=True)
        for pin in select(pins, arch, SHIPPED_BINARIES):
            source = fetch(pin, TOOLS / arch)
            os.link(source, stage / arch / pin.name)
    return stage


def trivy(mode: str, target: str, **kwargs) -> int:
    argv = trivy_command(str(TOOLS / HOST_ARCH / "trivy"), mode, target, **kwargs)
    if mode == "fs":
        argv[-1:-1] = [arg for d in SKIP_DIRS for arg in ("--skip-dirs", d)]
    return subprocess.run(argv, cwd=ROOT).returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "dist" / "scan")
    parser.add_argument("--write-vex", action="store_true", help="rewrite the VEX document instead of checking it")
    args = parser.parse_args()
    configure_logging()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    targets = {"source": ("fs", "."), "binaries": ("rootfs", str(stage_binaries(out)))}

    # 1. Raw scans: what the scanner reports, nothing suppressed.
    for index, (name, (mode, target)) in enumerate(targets.items()):
        if trivy(mode, target, fmt="json", output=str(out / f"{name}.json"), skip_db_update=index > 0) != 0:
            log.error("Trivy scan failed", target=name)
            sys.exit(1)

    # 2. Reviewed VEX: each statement answers a raw finding, and its evidence holds.
    try:
        vex.build(statements=STATEMENTS, scans=[out / f"{n}.json" for n in targets], tools_dir=TOOLS,
                  out=VEX_DOC, check=not args.write_vex)
    except vex.VexError as error:
        log.error("VEX check failed", error=str(error))
        sys.exit(1)

    # 3. Gate: SARIF with VEX applied; any finding left fails the run.
    remaining = []
    for name, (mode, target) in targets.items():
        code = trivy(mode, target, fmt="sarif", output=str(out / f"{name}.sarif"), skip_db_update=True,
                     vex=str(VEX_DOC) if VEX_DOC.exists() else None, gate=True)
        if code == FINDINGS_EXIT:
            remaining.append(name)
        elif code != 0:
            log.error("Trivy scan failed", target=name, exit_code=code)
            sys.exit(1)
    if remaining:
        log.error("Unaddressed vulnerabilities", targets=",".join(remaining), sarif=str(out))
        sys.exit(1)
    log.info("Scan clean after VEX", targets=",".join(targets), sarif=str(out))


if __name__ == "__main__":
    main()
