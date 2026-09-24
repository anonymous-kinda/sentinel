"""Trivy: the one place its argv is built, and a reader for its JSON reports."""

from __future__ import annotations

import dataclasses

# Exit code for "findings remain after VEX". Trivy itself exits 1 when it fails,
# so a crashed scan can never be mistaken for a gate decision (or a pass).
FINDINGS_EXIT = 5


@dataclasses.dataclass(frozen=True)
class Finding:
    vulnerability: str
    purl: str
    target: str
    severity: str


def findings(report: dict) -> list[Finding]:
    """Every vulnerability in a Trivy JSON report (SchemaVersion 2)."""
    out = []
    for result in report.get("Results") or []:
        for v in result.get("Vulnerabilities") or []:
            purl = (v.get("PkgIdentifier") or {}).get("PURL", "")
            out.append(Finding(v["VulnerabilityID"], purl, result.get("Target", ""), v.get("Severity", "UNKNOWN")))
    return out


def trivy_command(
    trivy: str,
    mode: str,
    target: str,
    *,
    fmt: str,
    output: str,
    vex: str | None = None,
    gate: bool = False,
    skip_db_update: bool = False,
) -> list[str]:
    """`trivy fs|rootfs` for vulnerabilities only, with telemetry and update checks off.

    A raw scan (no VEX, no gate) records what the scanner found. A gating
    scan applies the reviewed VEX document and exits FINDINGS_EXIT on anything left.
    """
    argv = [
        trivy, mode, "--scanners", "vuln", "--format", fmt, "--output", output,
        "--disable-telemetry", "--skip-version-check", "--no-progress",
    ]
    if skip_db_update:
        argv.append("--skip-db-update")
    if vex:
        argv += ["--vex", vex]
    if gate:
        argv += ["--exit-code", str(FINDINGS_EXIT)]
    return [*argv, target]
