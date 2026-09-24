"""SHA256SUMS manifests, byte-compatible with `sha256sum --strict -c`."""

from __future__ import annotations

import hashlib
import pathlib

MANIFEST = "SHA256SUMS"


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_text(root: pathlib.Path, exclude: frozenset[str] = frozenset({MANIFEST})) -> str:
    """One `<sha256>  <relative/posix/path>` line per file under root, sorted."""
    lines = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel not in exclude:
            lines.append(f"{sha256_file(path)}  {rel}")
    return "\n".join(lines) + "\n"


def write_manifest(root: pathlib.Path) -> pathlib.Path:
    out = root / MANIFEST
    out.write_text(manifest_text(root))
    return out
