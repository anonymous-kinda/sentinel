"""Evidence readers: pytest JUnit XML, DDIL harness results, OpenSCAP XCCDF results.

Wrong raises (EvidenceError): a file that cannot be parsed, a run with no
time, a result value this code does not understand. Any of those would let
the assessment claim something it cannot support.

Incomplete degrades: an empty harness directory, a scan time without a UTC
offset, a rule result the benchmark does not describe. Each is logged and
the assessment says what it did not see.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import pathlib
import re
import xml.etree.ElementTree as ET

from sentinel.obs import get_logger

log = get_logger(__name__)

XCCDF_RESULTS = frozenset(
    {"pass", "fail", "error", "unknown", "notapplicable", "notchecked", "notselected", "informational", "fixed"}
)
_VULN_KEY = re.compile(r"(SV-\d+)")


class EvidenceError(ValueError):
    """Evidence that would make the assessment wrong. Nothing is generated from it."""


# ---------------------------------------------------------------------- JUnit
@dataclasses.dataclass(frozen=True)
class CaseResult:
    classname: str
    name: str
    outcome: str  # passed | failed | error | skipped
    message: str = ""


@dataclasses.dataclass(frozen=True)
class JUnitRun:
    started: dt.datetime
    duration_s: float
    cases: tuple[CaseResult, ...]


def read_junit(path: pathlib.Path) -> JUnitRun:
    root = _parse_xml(path)
    suites = [root] if _local(root.tag) == "testsuite" else [e for e in root if _local(e.tag) == "testsuite"]
    if not suites:
        raise EvidenceError(f"{path.name}: no testsuite element")
    starts = [_suite_start(path, suite) for suite in suites]
    cases = tuple(_case(e) for suite in suites for e in suite.iter() if _local(e.tag) == "testcase")
    if not cases:
        raise EvidenceError(f"{path.name}: no testcases; an empty run is not evidence")
    return JUnitRun(
        started=min(starts),
        duration_s=sum(float(s.get("time") or 0.0) for s in suites),
        cases=cases,
    )


def _suite_start(path: pathlib.Path, suite: ET.Element) -> dt.datetime:
    stamp = suite.get("timestamp")
    if not stamp:
        raise EvidenceError(f"{path.name}: testsuite has no timestamp; when the evidence was collected is unknown")
    started = dt.datetime.fromisoformat(stamp)
    if started.tzinfo is None:
        raise EvidenceError(f"{path.name}: testsuite timestamp {stamp} has no UTC offset")
    return started


def _case(element: ET.Element) -> CaseResult:
    outcome, message = "passed", ""
    for child in element:
        kind = _local(child.tag)
        if kind in {"error", "failure", "skipped"}:
            candidate = {"error": "error", "failure": "failed", "skipped": "skipped"}[kind]
            if _severity(candidate) > _severity(outcome):
                outcome, message = candidate, child.get("message") or ""
    return CaseResult(element.get("classname") or "", element.get("name") or "", outcome, message)


def _severity(outcome: str) -> int:
    return ("passed", "skipped", "failed", "error").index(outcome)


# -------------------------------------------------------------------- harness
@dataclasses.dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    failed_assertions: tuple[str, ...]
    ran_at: str


def read_harness(directory: pathlib.Path) -> dict[str, ScenarioResult]:
    if not directory.is_dir():
        raise EvidenceError(f"harness results directory {directory} not found")
    results = {}
    for path in sorted(directory.glob("*.json")):
        result = _scenario(path)
        results[result.name] = result
    if not results:
        log.warning("Harness results directory is empty", directory=str(directory))
    return results


def _scenario(path: pathlib.Path) -> ScenarioResult:
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"{path.name}: not JSON ({exc.msg})") from exc
    if not isinstance(raw.get("assertions"), list) or "scenario" not in raw:
        raise EvidenceError(f"{path.name}: harness result needs 'scenario' and 'assertions'")
    failed = tuple(
        a["name"] + (f" ({a['detail']})" if a.get("detail") else "") for a in raw["assertions"] if not a["passed"]
    )
    return ScenarioResult(
        name=str(raw["scenario"]).lower(),
        passed=bool(raw.get("passed")) and not failed,
        failed_assertions=failed,
        ran_at=str(raw.get("ran_at", "")),
    )


# ---------------------------------------------------------------------- XCCDF
@dataclasses.dataclass(frozen=True)
class RuleResult:
    rule_ref: str
    vuln_key: str | None  # "SV-270647": the rule id without its revision
    stig_id: str | None  # "UBTU-24-100030", when the results file describes the rule
    result: str


@dataclasses.dataclass(frozen=True)
class ScanRun:
    target: str
    profile: str
    started: dt.datetime | None
    finished: dt.datetime | None
    results: tuple[RuleResult, ...]


def read_xccdf(path: pathlib.Path) -> ScanRun:
    root = _parse_xml(path)
    test_result = next((e for e in root.iter() if _local(e.tag) == "TestResult"), None)
    if test_result is None:
        raise EvidenceError(f"{path.name}: no TestResult element; this is a benchmark, not scan results")
    versions = {
        e.get("id"): _text(e, "version") for e in root.iter() if _local(e.tag) == "Rule" and e.get("id")
    }
    results = tuple(_rule_result(path, e, versions) for e in test_result if _local(e.tag) == "rule-result")
    return ScanRun(
        target=_text(test_result, "target") or "",
        profile=next((e.get("idref", "") for e in test_result if _local(e.tag) == "profile"), ""),
        started=_scan_time(path, test_result.get("start-time")),
        finished=_scan_time(path, test_result.get("end-time")),
        results=results,
    )


def _rule_result(path: pathlib.Path, element: ET.Element, versions: dict) -> RuleResult:
    ref = element.get("idref", "")
    result = (_text(element, "result") or "").strip()
    if result not in XCCDF_RESULTS:
        raise EvidenceError(f"{path.name}: rule {ref} has result '{result}', which is not an XCCDF result value")
    match = _VULN_KEY.search(ref)
    return RuleResult(ref, match.group(1) if match else None, versions.get(ref), result)


def _scan_time(path: pathlib.Path, value: str | None) -> dt.datetime | None:
    if not value:
        return None
    stamp = dt.datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        log.warning("Scan time has no UTC offset", file=path.name, value=value)
        return None
    return stamp


# -------------------------------------------------------------------- helpers
def _parse_xml(path: pathlib.Path) -> ET.Element:
    if not path.is_file():
        raise EvidenceError(f"{path} not found")
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise EvidenceError(f"{path.name}: XML is not well-formed ({exc})") from exc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element, child: str) -> str | None:
    found = next((e for e in element if _local(e.tag) == child), None)
    return None if found is None else found.text
