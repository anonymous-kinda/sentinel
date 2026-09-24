#!/usr/bin/env python3
"""Download pinned tools from deploy/tools.lock into .tools/<arch>/, verified.

    python scripts/fetch_tools.py [--arch x86_64|aarch64] [name ...]

A hash mismatch is fatal and nothing is written. Already-present tools
whose recorded digest matches are not downloaded again. noarch pins (trust
roots) land in .tools/noarch/. The logic lives in supplychain.toolslock.
"""

from __future__ import annotations

import argparse
import pathlib
import platform
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from supplychain.toolslock import LockError, fetch, read_lock, select  # noqa: I001

LOCK = ROOT / "deploy" / "tools.lock"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", default=platform.machine())
    parser.add_argument("names", nargs="*")
    args = parser.parse_args()
    arch = {"amd64": "x86_64", "arm64": "aarch64"}.get(args.arch, args.arch)
    try:
        wanted = select(read_lock(LOCK), arch, args.names)
        if not wanted:
            sys.exit(f"no tools for arch {arch}")
        for pin in wanted:
            path = fetch(pin, ROOT / ".tools" / pin.arch)
            print(f"{pin.name:12} {pin.version:8} {pin.arch:8} -> {path.relative_to(ROOT)}")
    except LockError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
