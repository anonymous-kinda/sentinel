"""OpenVEX 0.2.0 documents assembled from reviewed statements (deploy/vex/statements.toml).

    python -m supplychain.vex --statements deploy/vex/statements.toml \\
        --scan dist/scan/source.json --scan dist/scan/binaries.json \\
        --tools-dir .tools --out deploy/vex/sentinel.openvex.json [--check]

A statement is published only if (1) a raw scan actually reported the
finding it answers, (2) it carries an OpenVEX justification and a written
impact statement, and (3) its evidence check, if any, still holds against
the shipped binaries. Anything else raises. The schema requires at least one
statement, so with none the document is removed rather than written empty.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys
import tomllib
from collections.abc import Iterable, Sequence

from sentinel.obs import configure_logging, get_logger

from .evidence import EvidenceError, GoPackageAbsent
from .trivy import Finding, findings

log = get_logger(__name__)

CONTEXT = "https://openvex.dev/ns/v0.2.0"
STATUSES = ("not_affected", "affected", "fixed", "under_investigation")
JUSTIFICATIONS = (
    "component_not_present",
    "vulnerable_code_not_present",
    "vulnerable_code_not_in_execute_path",
    "vulnerable_code_cannot_be_controlled_by_adversary",
    "inline_mitigations_already_exist",
)
_DOCUMENT_KEYS = {"id", "author", "role", "version", "timestamp"}
_STATEMENT_KEYS = {
    "vulnerability", "products", "subcomponents", "status", "justification",
    "impact_statement", "action_statement", "timestamp", "evidence",
}
_EVIDENCE_KEYS = {"kind", "package", "control", "binaries"}


class VexError(Exception):
    """Reviewed VEX input is invalid, stale, unsupported by evidence, or out of date."""


@dataclasses.dataclass(frozen=True)
class DocumentMeta:
    id: str
    author: str
    role: str
    version: int
    timestamp: str


@dataclasses.dataclass(frozen=True)
class Statement:
    vulnerability: str
    products: tuple[str, ...]
    subcomponents: tuple[str, ...]
    status: str
    timestamp: str
    justification: str | None = None
    impact_statement: str | None = None
    action_statement: str | None = None
    evidence: GoPackageAbsent | None = None
    evidence_binaries: tuple[str, ...] = ()


# ----------------------------------------------------------------- loading ----
def load(text: str) -> tuple[DocumentMeta, list[Statement]]:
    data = tomllib.loads(text)
    _reject_unknown(data, {"document", "statement"}, "top level")
    doc = data.get("document") or {}
    _reject_unknown(doc, _DOCUMENT_KEYS, "[document]")
    missing = _DOCUMENT_KEYS - set(doc)
    if missing:
        raise VexError(f"[document] is missing {sorted(missing)}")
    meta = DocumentMeta(doc["id"], doc["author"], doc["role"], int(doc["version"]), doc["timestamp"])
    return meta, [_statement(raw, i) for i, raw in enumerate(data.get("statement", []), start=1)]


def _statement(raw: dict, number: int) -> Statement:
    where = f"statement {number} ({raw.get('vulnerability', '?')})"
    _reject_unknown(raw, _STATEMENT_KEYS, where)
    for key in ("vulnerability", "products", "status", "timestamp"):
        if not raw.get(key):
            raise VexError(f"{where}: {key} is required")
    status = raw["status"]
    if status not in STATUSES:
        raise VexError(f"{where}: status must be one of {STATUSES}")
    if status == "not_affected":
        if raw.get("justification") not in JUSTIFICATIONS:
            raise VexError(f"{where}: not_affected needs a justification from {JUSTIFICATIONS}")
        if not raw.get("impact_statement"):
            raise VexError(f"{where}: not_affected needs an impact_statement saying why")
    if status == "affected" and not raw.get("action_statement"):
        raise VexError(f"{where}: affected needs an action_statement")
    evidence, binaries = _evidence(raw.get("evidence"), where)
    return Statement(
        vulnerability=raw["vulnerability"],
        products=tuple(raw["products"]),
        subcomponents=tuple(raw.get("subcomponents", ())),
        status=status,
        timestamp=raw["timestamp"],
        justification=raw.get("justification"),
        impact_statement=raw.get("impact_statement"),
        action_statement=raw.get("action_statement"),
        evidence=evidence,
        evidence_binaries=binaries,
    )


def _evidence(raw: dict | None, where: str) -> tuple[GoPackageAbsent | None, tuple[str, ...]]:
    if raw is None:
        return None, ()
    _reject_unknown(raw, _EVIDENCE_KEYS, f"{where} evidence")
    if raw.get("kind") != "go-package-absent":
        raise VexError(f"{where}: unsupported evidence kind {raw.get('kind')!r}")
    if not raw.get("binaries"):
        raise VexError(f"{where}: evidence needs at least one binary")
    return GoPackageAbsent(raw["package"], raw["control"]), tuple(raw["binaries"])


def _reject_unknown(table: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise VexError(f"{where}: unknown key(s) {unknown}")


# ----------------------------------------------------------------- checking ----
def stale(statements: Iterable[Statement], found: Iterable[Finding]) -> list[Statement]:
    """Statements that answer no finding a scan actually produced."""
    reported = {(f.vulnerability, f.purl) for f in found}
    return [
        s for s in statements
        if not any((s.vulnerability, purl) in reported for purl in (*s.subcomponents, *s.products))
    ]


def verify_evidence(statements: Iterable[Statement], tools_dir: pathlib.Path) -> None:
    for s in statements:
        for binary in s.evidence_binaries:
            try:
                s.evidence.verify(tools_dir / binary)  # type: ignore[union-attr]
            except EvidenceError as error:
                raise VexError(f"{s.vulnerability}: evidence does not hold: {error}") from error
            log.info("VEX evidence verified", vulnerability=s.vulnerability, binary=binary)


# ----------------------------------------------------------------- document ----
def document(meta: DocumentMeta, statements: Sequence[Statement]) -> dict:
    if not statements:
        raise VexError("OpenVEX 0.2.0 requires at least one statement")
    doc = {
        "@context": CONTEXT,
        "@id": meta.id,
        "author": meta.author,
        "role": meta.role,
        "timestamp": meta.timestamp,
        "version": meta.version,
        "statements": [_statement_json(s) for s in statements],
    }
    validate_document(doc)
    return doc


def _statement_json(s: Statement) -> dict:
    subcomponents = [{"@id": purl} for purl in s.subcomponents]
    products = [{"@id": purl, **({"subcomponents": subcomponents} if subcomponents else {})} for purl in s.products]
    out: dict = {"vulnerability": {"name": s.vulnerability}, "timestamp": s.timestamp, "products": products,
                 "status": s.status}
    for key in ("justification", "impact_statement", "action_statement"):
        value = getattr(s, key)
        if value:
            out[key] = value
    return out


def validate_document(doc: dict) -> None:
    """The rules of openvex_json_schema_0.2.0 that this generator could break."""
    for key in ("@context", "@id", "author", "timestamp", "version", "statements"):
        if key not in doc:
            raise VexError(f"OpenVEX document is missing {key}")
    if not doc["statements"]:
        raise VexError("OpenVEX 0.2.0 requires at least one statement")
    seen = []
    for st in doc["statements"]:
        if st in seen:
            raise VexError("OpenVEX statements must be unique")
        seen.append(st)
        if st.get("status") not in STATUSES or "name" not in st.get("vulnerability", {}):
            raise VexError("OpenVEX statement needs a vulnerability name and a valid status")
        if st.get("justification") and st["justification"] not in JUSTIFICATIONS:
            raise VexError("OpenVEX justification outside the vocabulary")
        if st["status"] == "not_affected" and not (st.get("justification") or st.get("impact_statement")):
            raise VexError("not_affected needs a justification or impact_statement")
        if st["status"] == "affected" and not st.get("action_statement"):
            raise VexError("affected needs an action_statement")


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2) + "\n"


# ----------------------------------------------------------------- pipeline ----
def build(
    *,
    statements: pathlib.Path,
    scans: Sequence[pathlib.Path],
    tools_dir: pathlib.Path,
    out: pathlib.Path,
    check: bool = False,
) -> dict | None:
    meta, reviewed = load(statements.read_text())
    found = [f for scan in scans for f in findings(json.loads(scan.read_text()))]
    unanswered = stale(reviewed, found)
    if unanswered:
        ids = ", ".join(s.vulnerability for s in unanswered)
        raise VexError(f"stale VEX statement(s), no scan reported them: {ids} - remove or update them")
    verify_evidence(reviewed, tools_dir)
    if not reviewed:
        if check and out.exists():
            raise VexError(f"{out} is out of date: there are no statements, so it must not exist")
        out.unlink(missing_ok=True)
        log.info("No VEX statements, no document written", findings=len(found))
        return None
    doc = document(meta, reviewed)
    text = render(doc)
    if check:
        if not out.exists() or out.read_text() != text:
            raise VexError(f"{out} is out of date: run `make vex` and commit the result")
    else:
        out.write_text(text)
    log.info("VEX document assembled", statements=len(reviewed), findings=len(found), path=str(out))
    return doc


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m supplychain.vex")
    parser.add_argument("--statements", type=pathlib.Path, required=True)
    parser.add_argument("--scan", type=pathlib.Path, action="append", default=[])
    parser.add_argument("--tools-dir", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--check", action="store_true", help="fail if --out differs instead of writing it")
    args = parser.parse_args(argv)
    configure_logging()
    try:
        build(statements=args.statements, scans=args.scan, tools_dir=args.tools_dir, out=args.out, check=args.check)
    except VexError as error:
        log.error("VEX assembly refused", error=str(error))
        sys.exit(1)


if __name__ == "__main__":
    main()
