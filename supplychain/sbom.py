"""SBOM generation (syft argv) and the completeness gate on its output."""

from __future__ import annotations

from collections.abc import Mapping


class SbomError(Exception):
    """An SBOM is unreadable, empty, or missing a component that ships."""


def component_names(doc: dict) -> set[str]:
    if "spdxVersion" in doc:
        return {p["name"] for p in doc.get("packages", [])}
    if doc.get("bomFormat") == "CycloneDX":
        # syft also lists each installed file as a `file` component; those are not packages
        return {c["name"] for c in doc.get("components", []) if c.get("type") != "file"}
    raise SbomError("document is neither SPDX nor CycloneDX JSON")


def require_components(doc: dict, required: set[str], label: str) -> int:
    """Raise unless the SBOM is non-empty and lists every required component."""
    names = component_names(doc)
    if not names:
        raise SbomError(f"{label}: SBOM has no components")
    missing = sorted(required - names)
    if missing:
        raise SbomError(f"{label}: SBOM is missing {', '.join(missing)}")
    return len(names)


def syft_command(syft: str, source_dir: str, *, name: str, version: str, outputs: Mapping[str, str]) -> list[str]:
    """One catalog pass, every requested format (e.g. spdx-json, cyclonedx-json)."""
    argv = [syft, "scan", f"dir:{source_dir}", "--source-name", name, "--source-version", version, "--quiet"]
    for fmt, path in outputs.items():
        argv += ["-o", f"{fmt}={path}"]
    return argv
