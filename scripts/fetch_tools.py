#!/usr/bin/env python3
"""Download pinned tools from deploy/tools.lock into .tools/<arch>/, verified.

    python scripts/fetch_tools.py [--arch x86_64|aarch64] [name ...]

A hash mismatch is fatal and nothing is written. Already-present tools
whose recorded digest matches are not downloaded again.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import pathlib
import platform
import sys
import tarfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCK = ROOT / "deploy" / "tools.lock"


def entries():
    for line in LOCK.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, version, arch, sha, url, member = line.split()
        yield {"name": name, "version": version, "arch": arch, "sha256": sha, "url": url, "member": member}


def fetch(entry: dict, dest_dir: pathlib.Path) -> pathlib.Path:
    dest = dest_dir / entry["name"]
    stamp = dest_dir / f".{entry['name']}.sha256"
    if dest.exists() and stamp.exists() and stamp.read_text().strip() == entry["sha256"]:
        return dest
    with urllib.request.urlopen(entry["url"], timeout=120) as response:
        blob = response.read()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != entry["sha256"]:
        sys.exit(f"SHA-256 MISMATCH for {entry['name']} {entry['arch']}: got {digest}, pinned {entry['sha256']}")
    if entry["member"] == "-":
        payload = blob
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            payload = tar.extractfile(entry["member"]).read()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    dest.chmod(0o755)
    stamp.write_text(entry["sha256"] + "\n")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", default=platform.machine())
    parser.add_argument("names", nargs="*")
    args = parser.parse_args()
    arch = {"amd64": "x86_64", "arm64": "aarch64"}.get(args.arch, args.arch)
    wanted = [e for e in entries() if e["arch"] == arch and (not args.names or e["name"] in args.names)]
    if not wanted:
        sys.exit(f"no tools for arch {arch} matching {args.names}")
    for entry in wanted:
        path = fetch(entry, ROOT / ".tools" / arch)
        print(f"{entry['name']:12} {entry['version']:8} {arch:8} -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
