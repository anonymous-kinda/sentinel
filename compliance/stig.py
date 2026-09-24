"""DISA STIG benchmark and CCI list, read from the vendored upstream files.

Rule titles, severities and CCIs come from DISA's XCCDF; the link from a CCI
to NIST SP 800-53 Rev 5 comes from DISA's CCI list. Sentinel transcribes
neither, so neither can drift from its source.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re
import xml.etree.ElementTree as ET
import zipfile

from .inputs import ScanRun
from .sources import StigDecisions

_XCCDF = {"x": "http://checklists.nist.gov/xccdf/1.1"}
_CCI = {"c": "http://iase.disa.mil/cci"}
_REV5 = "NIST SP 800-53 Revision 5"
_REFERENCE = re.compile(r"^([A-Z]{2})-(\d+)(?: \((\d+)\))?")
_RELEASE = re.compile(r"Release:\s*(\d+)\s+Benchmark Date:\s*(.+)$")


@dataclasses.dataclass(frozen=True)
class StigRule:
    stig_id: str
    vuln_id: str
    rule_id: str
    severity: str
    title: str
    ccis: tuple[str, ...]

    @property
    def vuln_key(self) -> str:
        """The rule id without its revision: what a scanner's rule-result names."""
        return self.rule_id.split("r", 1)[0]


@dataclasses.dataclass(frozen=True)
class Benchmark:
    title: str
    release: str
    date: str
    rules: dict[str, StigRule]

    def by_vuln_key(self, key: str) -> StigRule | None:
        return next((r for r in self.rules.values() if r.vuln_key == key), None)


def load_benchmark(path: pathlib.Path) -> Benchmark:
    root = ET.parse(path).getroot()
    release_info = next(p.text for p in root.findall("x:plain-text", _XCCDF) if p.get("id") == "release-info")
    number, date = _RELEASE.match(release_info.strip()).groups()
    rules = {}
    for group in root.findall("x:Group", _XCCDF):
        rule = group.find("x:Rule", _XCCDF)
        stig_id = rule.findtext("x:version", namespaces=_XCCDF)
        rules[stig_id] = StigRule(
            stig_id=stig_id,
            vuln_id=group.get("id"),
            rule_id=rule.get("id"),
            severity=rule.get("severity"),
            title=rule.findtext("x:title", namespaces=_XCCDF),
            ccis=tuple(i.text for i in rule.findall("x:ident", _XCCDF) if i.text.startswith("CCI-")),
        )
    return Benchmark(
        title=root.findtext("x:title", namespaces=_XCCDF),
        release=f"V{root.findtext('x:version', namespaces=_XCCDF)}R{number}",
        date=date.strip(),
        rules=rules,
    )


def load_cci_rev5(path: pathlib.Path) -> dict[str, tuple[str, ...]]:
    """CCI id -> its NIST SP 800-53 Rev 5 references, as DISA publishes them."""
    with zipfile.ZipFile(path) as archive, archive.open("U_CCI_List.xml") as stream:
        root = ET.parse(stream).getroot()
    return {
        item.get("id"): tuple(
            r.get("index") for r in item.iterfind("c:references/c:reference", _CCI) if r.get("title") == _REV5
        )
        for item in root.iterfind(".//c:cci_item", _CCI)
    }


def control_ids(references: tuple[str, ...]) -> tuple[str, ...]:
    """'IA-5 (1) (c)' -> 'ia-5.1'; statement letters are dropped, enhancements kept."""
    ids = set()
    for ref in references:
        match = _REFERENCE.match(ref)
        if not match:
            raise ValueError(f"'{ref}' is not an 800-53 reference")
        family, number, enhancement = match.groups()
        ids.add(f"{family.lower()}-{number}" + (f".{enhancement}" if enhancement else ""))
    return tuple(sorted(ids))


# ---------------------------------------------------------------- catalog
@dataclasses.dataclass(frozen=True)
class StigCatalog:
    """The benchmark and DISA's CCI-to-800-53 map, loaded once per run."""

    benchmark: Benchmark
    rev5: dict[str, tuple[str, ...]]

    def rule(self, stig_id: str) -> StigRule:
        try:
            return self.benchmark.rules[stig_id]
        except KeyError:
            raise ValueError(f"{stig_id} is not a rule in {self.benchmark.release}") from None

    def controls(self, rule: StigRule) -> tuple[str, ...]:
        return control_ids(tuple(ref for cci in rule.ccis for ref in self.rev5.get(cci, ())))


def load_stig_catalog(root: pathlib.Path, decisions: StigDecisions) -> StigCatalog:
    """Load the vendored benchmark and CCI list; every rule stig.toml decides must exist in it."""
    catalog = StigCatalog(load_benchmark(root / decisions.xccdf), load_cci_rev5(root / decisions.cci_list))
    for stig_id in decisions.decided():
        catalog.rule(stig_id)
    return catalog


# ------------------------------------------------------------------ triage
PASSING = frozenset({"pass", "fixed"})
UNEVALUATED = frozenset({"error", "unknown"})


@dataclasses.dataclass(frozen=True)
class TriagedResult:
    stig_id: str  # the STIG id, or the scanner's rule reference if the benchmark does not know it
    rule: StigRule | None
    result: str
    decision: str | None  # applied | not-applicable | <deviation key> | None (never decided)


def triage(scan: ScanRun, catalog: StigCatalog, decisions: StigDecisions) -> tuple[TriagedResult, ...]:
    """Name each scanned rule by its STIG id and attach what stig.toml decided about it."""
    triaged = []
    for result in scan.results:
        rule = catalog.benchmark.rules.get(result.stig_id) if result.stig_id else None
        rule = rule or (catalog.benchmark.by_vuln_key(result.vuln_key) if result.vuln_key else None)
        stig_id = rule.stig_id if rule else (result.stig_id or result.rule_ref)
        triaged.append(TriagedResult(stig_id, rule, result.result, decisions.decision(stig_id)))
    return tuple(triaged)
