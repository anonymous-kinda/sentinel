"""Match the evidence each control cites against what a CI run actually did.

Citation states:

    passed        every matched case passed (skips noted)
    failed        a matched case failed or errored, or the cited scenario failed
    missing       the cited test matched nothing, or only skipped cases:
                  the SSP cites evidence this run does not contain
    not-supplied  harness results were not given to this run (they come from
                  their own workflow); recorded, not held against the control
"""

from __future__ import annotations

import collections
import dataclasses
import datetime as dt

from sentinel.obs import get_logger

from .inputs import CaseResult, JUnitRun, ScanRun, ScenarioResult
from .sources import Control, Sources

log = get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class RunEvidence:
    """Everything one CI run contributes to the assessment."""

    run: JUnitRun
    controls: tuple[ControlEvidence, ...]
    unmapped: tuple[CaseResult, ...]
    harness_supplied: bool
    scan: ScanRun | None

    @property
    def ended(self):
        return self.run.started + dt.timedelta(seconds=self.run.duration_s)


def collect(
    sources: Sources, run: JUnitRun, harness: dict[str, ScenarioResult] | None, scan: ScanRun | None
) -> RunEvidence:
    controls = list(sources.controls)
    return RunEvidence(
        run=run,
        controls=assess(controls, run, harness),
        unmapped=unmapped_failures(controls, run),
        harness_supplied=harness is not None,
        scan=scan,
    )


@dataclasses.dataclass(frozen=True)
class CitationResult:
    citation: str
    kind: str  # test | harness
    state: str  # passed | failed | missing | not-supplied
    detail: str
    components: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ControlEvidence:
    control: Control
    citations: tuple[CitationResult, ...]

    @property
    def failed(self) -> tuple[CitationResult, ...]:
        return tuple(c for c in self.citations if c.state == "failed")

    @property
    def missing(self) -> tuple[CitationResult, ...]:
        return tuple(c for c in self.citations if c.state == "missing")

    @property
    def observed(self) -> bool:
        return any(c.state != "not-supplied" for c in self.citations)

    @property
    def satisfied(self) -> bool:
        return self.observed and not self.failed and not self.missing


def cites(citation: str, case: CaseResult) -> bool:
    """Does this pytest node id (file, file::function, file::Class[::method]) cover the case?"""
    path, _, rest = citation.partition("::")
    module = path.removesuffix(".py").replace("/", ".")
    if not rest:
        return case.classname == module or case.classname.startswith(module + ".")
    parts = rest.split("::")
    if len(parts) == 2:
        return case.classname == f"{module}.{parts[0]}" and _same_function(case.name, parts[1])
    (name,) = parts
    as_function = case.classname == module and _same_function(case.name, name)
    return as_function or case.classname == f"{module}.{name}"


def _same_function(case_name: str, function: str) -> bool:
    return case_name == function or case_name.startswith(function + "[")


def assess(
    controls: list[Control], run: JUnitRun, harness: dict[str, ScenarioResult] | None
) -> tuple[ControlEvidence, ...]:
    results = tuple(ControlEvidence(c, _citations(c, run, harness)) for c in controls)
    for result in results:
        if result.missing:
            log.warning("Cited evidence missing from run", control=result.control.id, missing=len(result.missing))
    return results


def _citations(control: Control, run: JUnitRun, harness: dict[str, ScenarioResult] | None) -> tuple:
    by_citation: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for contribution in control.contributions:
        for test in contribution.tests:
            by_citation[("test", test)].append(contribution.component)
        for scenario in contribution.harness:
            by_citation[("harness", scenario)].append(contribution.component)
    return tuple(
        _test_result(citation, run, tuple(components))
        if kind == "test"
        else _harness_result(citation, harness, tuple(components))
        for (kind, citation), components in by_citation.items()
    )


def _test_result(citation: str, run: JUnitRun, components: tuple[str, ...]) -> CitationResult:
    cases = [c for c in run.cases if cites(citation, c)]
    counts = collections.Counter(c.outcome for c in cases)
    broken = [c for c in cases if c.outcome in {"failed", "error"}]
    if broken:
        detail = f"{len(broken)} of {len(cases)} failed: " + "; ".join(f"{c.name}: {c.message}" for c in broken)
        return CitationResult(citation, "test", "failed", detail, components)
    if counts["passed"]:
        return CitationResult(citation, "test", "passed", _plural(counts["passed"], "passed"), components)
    detail = _plural(counts["skipped"], "skipped") if counts["skipped"] else "not in this run"
    return CitationResult(citation, "test", "missing", detail, components)


def _harness_result(
    scenario: str, harness: dict[str, ScenarioResult] | None, components: tuple[str, ...]
) -> CitationResult:
    if harness is None:
        return CitationResult(scenario, "harness", "not-supplied", "harness results not supplied", components)
    result = harness.get(scenario)
    if result is None:
        return CitationResult(scenario, "harness", "not-supplied", "scenario not in the supplied results", components)
    if not result.passed:
        return CitationResult(scenario, "harness", "failed", "; ".join(result.failed_assertions), components)
    return CitationResult(scenario, "harness", "passed", f"all assertions passed ({result.ran_at})", components)


def _plural(count: int, verb: str) -> str:
    return f"{count} case{'s' if count != 1 else ''} {verb}"


def unmapped_failures(controls: list[Control], run: JUnitRun) -> tuple[CaseResult, ...]:
    """Failed or errored cases that no control cites: still weaknesses, still reported."""
    citations = [t for control in controls for c in control.contributions for t in c.tests]
    return tuple(
        case for case in run.cases
        if case.outcome in {"failed", "error"} and not any(cites(t, case) for t in citations)
    )
