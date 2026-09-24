"""Assessment results and POA&M from one CI run's evidence.

Assessment results: one observation per control with automated evidence,
one finding per control whose cited checks failed or are missing, and one
observation summarising a STIG scan when one is supplied.

POA&M: everything not yet true, most urgent first. Failing tests, evidence
the SSP cites that the run lacks, failed DDIL scenarios, STIG results the
decisions do not account for, the host baseline while no scan has verified
it, every contribution short of implemented, and every STIG deviation.
Deviations are *requested*, never approved: no authorizing official has
reviewed them.
"""

from __future__ import annotations

import collections
import dataclasses
from typing import Any

from .authored import reviewed_controls
from .evidence import CitationResult, ControlEvidence, RunEvidence, cites
from .inputs import CaseResult
from .oscal_common import (
    ASSESSMENT_PLAN,
    SSP,
    component_uuid,
    document,
    href,
    metadata,
    prop,
    stable_uuid,
    system_id,
    timestamp,
    tool_uuid,
    without_empty,
)
from .sources import Sources
from .stig import PASSING, UNEVALUATED, StigCatalog, StigRule, TriagedResult, triage

_TOOL = {"test": "ladder", "harness": "harness"}
_CATEGORY = {"high": "CAT I", "medium": "CAT II", "low": "CAT III"}
_SEVERITY_ORDER = ("low", "medium", "high")


def _origin(*assessment_keys: str) -> dict[str, Any]:
    return {"actors": [{"type": "tool", "actor-uuid": tool_uuid(k)} for k in assessment_keys]}


def _count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


# ============================================================ assessment results
def build_assessment_results(sources: Sources, evidence: RunEvidence, stig: StigCatalog) -> dict[str, Any]:
    started = timestamp(evidence.run.started)
    observed = [e for e in evidence.controls if e.citations]
    observations = [_control_observation(e, started) for e in observed]
    findings = [
        _finding(e, observation["uuid"], started)
        for e, observation in zip(observed, observations, strict=True)
        if e.failed or e.missing
    ]
    if evidence.unmapped:
        observations.append(_unmapped_observation(evidence, started))
    if evidence.scan is not None:
        observations.append(_scan_observation(sources, evidence, stig))
    result = without_empty({
        "uuid": stable_uuid("result", started),
        "title": f"Automated assessment of the test run started {started}",
        "description": _run_description(evidence),
        "start": started,
        "end": timestamp(evidence.ended),
        "reviewed-controls": reviewed_controls(sources),
        "observations": observations,
        "findings": findings,
    })
    return document("assessment-results", {
        "metadata": metadata(
            f"{sources.system.name} automated assessment results", sources.system.document.version, evidence.ended
        ),
        "import-ap": {"href": href(ASSESSMENT_PLAN)},
        "results": [result],
    })


def _run_description(evidence: RunEvidence) -> str:
    outcomes = collections.Counter(c.outcome for c in evidence.run.cases)
    satisfied = sum(e.satisfied for e in evidence.controls)
    observed = sum(e.observed for e in evidence.controls)
    return (
        f"pytest: {len(evidence.run.cases)} cases, {outcomes['passed']} passed, {outcomes['failed']} failed, "
        f"{outcomes['error']} errors, {outcomes['skipped']} skipped. "
        f"Controls with automated evidence in this run: {observed}; all cited checks passed for {satisfied}. "
        f"DDIL harness results {'supplied' if evidence.harness_supplied else 'not supplied'}; "
        f"STIG scan results {'supplied' if evidence.scan else 'not supplied'}."
    )


def _control_observation(evidence: ControlEvidence, started: str) -> dict[str, Any]:
    control = evidence.control
    kinds = [k for k in _TOOL if any(c.kind == k for c in evidence.citations)]
    components = list(dict.fromkeys(comp for c in evidence.citations for comp in c.components))
    return {
        "uuid": stable_uuid("observation", started, control.id),
        "title": f"{control.id.upper()}: automated evidence",
        # Passing checks are not a verdict on the control: say what the SSP claims.
        "description": f"{_observation_summary(evidence.citations)} "
                       f"The SSP states {control.id.upper()} as {control.status}.",
        "props": [prop("implementation-status", control.status)],
        "methods": ["TEST"],
        "types": ["control-objective"],
        "origins": [_origin(*(_TOOL[k] for k in kinds))],
        "subjects": [{"subject-uuid": component_uuid(c), "type": "component"} for c in components],
        "relevant-evidence": [_relevant(c) for c in evidence.citations],
        "collected": started,
    }


def _observation_summary(citations: tuple[CitationResult, ...]) -> str:
    supplied = [c for c in citations if c.state != "not-supplied"]
    n = len(supplied)
    parts = [
        f"{k} of {n} cited checks {verb}"
        for state, verb in (("failed", "failed"), ("missing", "missing from this run"))
        if (k := sum(c.state == state for c in supplied))
    ]
    if n and not parts:
        parts.append(f"{n} of {n} cited checks passed")
    if unsupplied := len(citations) - n:
        parts.append(f"{unsupplied} not supplied to this run")
    return "; ".join(parts) + "."


def _relevant(citation: CitationResult) -> dict[str, Any]:
    return {
        "description": f"{citation.citation}: {citation.detail}",
        "props": [prop(f"evidence-{citation.kind}", citation.citation), prop("result", citation.state)],
    }


def _finding(evidence: ControlEvidence, observation_uuid: str, started: str) -> dict[str, Any]:
    control = evidence.control
    problems = evidence.failed + evidence.missing
    return {
        "uuid": stable_uuid("finding", started, control.id),
        "title": f"{control.id.upper()} not satisfied",
        "description": "; ".join(f"{c.citation}: {c.detail}" for c in problems),
        "target": {
            "type": "objective-id",
            "target-id": f"{control.id}_obj",
            "status": {"state": "not-satisfied", "reason": "fail" if evidence.failed else "other"},
            "implementation-status": {"state": control.status},
        },
        "related-observations": [{"observation-uuid": observation_uuid}],
    }


def _unmapped_observation(evidence: RunEvidence, started: str) -> dict[str, Any]:
    return {
        "uuid": stable_uuid("observation", started, "unmapped-failures"),
        "title": "Failing tests no control cites",
        "description": "; ".join(f"{c.classname}::{c.name}: {c.message}" for c in evidence.unmapped),
        "methods": ["TEST"],
        "types": ["finding"],
        "origins": [_origin("ladder")],
        "collected": started,
    }


def _scan_observation(sources: Sources, evidence: RunEvidence, stig: StigCatalog) -> dict[str, Any]:
    scan = evidence.scan
    triaged = triage(scan, stig, sources.stig)
    by_result = collections.Counter(_result_class(t) for t in triaged)
    fails = collections.Counter(_decision_class(t.decision) for t in triaged if t.result == "fail")
    breakdown = ", ".join(
        _count(fails[key], singular, plural)
        for key, singular, plural in (
            ("applied", "applied rule", None),
            ("deviation", "documented deviation", None),
            ("open", "not yet addressed", "not yet addressed"),
            ("not-applicable", "marked not applicable", "marked not applicable"),
        )
        if fails[key]
    )
    parts = [
        f"{by_result['pass']} pass" if by_result["pass"] else "",
        f"{by_result['fail']} fail ({breakdown})" if by_result["fail"] else "",
        f"{by_result['not applicable']} not applicable" if by_result["not applicable"] else "",
        f"{by_result['not evaluated']} not evaluated" if by_result["not evaluated"] else "",
        f"{by_result['not checked']} not checked" if by_result["not checked"] else "",
    ]
    return {
        "uuid": stable_uuid("observation", timestamp(evidence.run.started), "stig-scan", scan.target),
        "title": f"STIG scan of {scan.target}",
        "description": f"{len(triaged)} rules evaluated with {scan.profile}: " + ", ".join(p for p in parts if p) + ".",
        "methods": ["TEST"],
        "origins": [_origin("stig-scan")],
        "subjects": [{"subject-uuid": component_uuid(sources.stig.component), "type": "component"}],
        "collected": timestamp(scan.started or evidence.run.started),
    }


def _result_class(t: TriagedResult) -> str:
    if t.result in PASSING:
        return "pass"
    if t.result == "fail":
        return "fail"
    if t.result == "notapplicable":
        return "not applicable"
    return "not evaluated" if t.result in UNEVALUATED else "not checked"


def _decision_class(decision: str | None) -> str:
    if decision in ("applied", "not-applicable"):
        return decision
    return "open" if decision is None else "deviation"


# ======================================================================== POA&M
@dataclasses.dataclass(frozen=True)
class _Entry:
    """One POA&M item and the risk that carries its status."""

    key: tuple[str, ...]
    title: str
    description: str
    statement: str
    status: str = "open"
    props: tuple[dict[str, str], ...] = ()
    origin: str = ""
    remarks: str = ""
    mitigation: str = ""
    remediation: str = ""

    def risk(self) -> dict[str, Any]:
        return without_empty({
            "uuid": stable_uuid("risk", *self.key),
            "title": self.title,
            "description": self.description,
            "statement": self.statement,
            "status": self.status,
            "mitigating-factors": (
                [{"uuid": stable_uuid("mitigation", *self.key), "description": self.mitigation}] if self.mitigation else []
            ),
            "remediations": (
                [{"uuid": stable_uuid("remediation", *self.key), "lifecycle": "planned",
                  "title": "Planned remediation", "description": self.remediation}]
                if self.remediation else []
            ),
        })

    def item(self) -> dict[str, Any]:
        return without_empty({
            "uuid": stable_uuid("poam-item", *self.key),
            "title": self.title,
            "description": self.description,
            "props": list(self.props),
            "origins": [_origin(self.origin)] if self.origin else [],
            "related-risks": [{"risk-uuid": stable_uuid("risk", *self.key)}],
            "remarks": self.remarks,
        })


def build_poam(sources: Sources, evidence: RunEvidence, stig: StigCatalog) -> dict[str, Any]:
    scan_entries = _scan_entries(sources, evidence, stig) if evidence.scan else [_unverified_entry(sources, stig)]
    entries = [
        *_test_failure_entries(evidence),
        *_missing_evidence_entries(evidence),
        *_harness_entries(evidence),
        *scan_entries,
        *_implementation_entries(sources),
        *_deviation_entries(sources, evidence, stig),
    ]
    return document("plan-of-action-and-milestones", {
        "metadata": metadata(
            f"{sources.system.name} plan of action and milestones", sources.system.document.version, evidence.ended
        ),
        "import-ssp": {"href": href(SSP)},
        "system-id": system_id(sources.system.short_name),
        "risks": [e.risk() for e in entries],
        "poam-items": [e.item() for e in entries],
    })


def _related(controls) -> tuple[dict[str, str], ...]:
    return tuple(prop("related-control", c) for c in dict.fromkeys(controls))


# ----------------------------------------------------------------- CI evidence
def _test_failure_entries(evidence: RunEvidence) -> list[_Entry]:
    broken = [c for c in evidence.run.cases if c.outcome in {"failed", "error"}]
    return [_test_failure(case, _citing_controls(evidence, case)) for case in broken]


def _citing_controls(evidence: RunEvidence, case: CaseResult) -> list[str]:
    return [
        e.control.id
        for e in evidence.controls
        if any(cites(t, case) for c in e.control.contributions for t in c.tests)
    ]


def _test_failure(case: CaseResult, controls: list[str]) -> _Entry:
    cited = ", ".join(c.upper() for c in controls)
    return _Entry(
        key=("test-failure", f"{case.classname}::{case.name}"),
        title=f"Failing test: {case.classname}::{case.name}",
        description=f"{case.outcome}: {case.message or 'no message'}",
        statement=(
            f"Cited by {cited}: their implementation statements are not supported by evidence while this fails."
            if controls else "No control cites this test; it is a defect in the system all the same."
        ),
        props=_related(controls),
        origin="ladder",
    )


def _missing_evidence_entries(evidence: RunEvidence) -> list[_Entry]:
    return [
        _Entry(
            key=("missing-evidence", e.control.id, c.citation),
            title=f"{e.control.id.upper()} cites evidence missing from the run: {c.citation}",
            description=(
                f"{c.citation}: {c.detail}. The SSP cites a check this run did not contain; "
                "it was renamed, deleted, skipped or not run."
            ),
            statement="An implementation statement cites evidence that does not exist.",
            props=_related([e.control.id]),
            origin="ladder",
        )
        for e in evidence.controls
        for c in e.missing
    ]


def _harness_entries(evidence: RunEvidence) -> list[_Entry]:
    failed: dict[str, list[str]] = collections.defaultdict(list)
    details: dict[str, str] = {}
    for e in evidence.controls:
        for c in e.failed:
            if c.kind == "harness":
                failed[c.citation].append(e.control.id)
                details[c.citation] = c.detail
    return [
        _Entry(
            key=("harness-failure", scenario),
            title=f"DDIL harness scenario failed: {scenario}",
            description=details[scenario],
            statement="Behaviour the SSP claims under a degraded link did not hold in the last harness run.",
            props=_related(controls),
            origin="harness",
        )
        for scenario, controls in failed.items()
    ]


# ------------------------------------------------------------------------ STIG
def _rule_line(rule: StigRule) -> str:
    return f"{rule.stig_id} ({rule.vuln_id}, {rule.rule_id}, {_CATEGORY[rule.severity]}): {rule.title}"


def _rule_props(rules: list[StigRule], stig: StigCatalog, component: str) -> tuple[dict[str, str], ...]:
    severity = max((r.severity for r in rules), key=_SEVERITY_ORDER.index)
    controls = [c for r in rules for c in stig.controls(r)]
    return (
        *(prop("stig-id", r.stig_id) for r in rules),
        prop("stig-severity", severity),
        prop("component", component),
        *_related(sorted(set(controls))),
    )


_SCAN_TITLES = {
    "applied": ("stig-regression", "Applied STIG rule fails on {target}: {id}",
                "A hardening setting the SSP relies on is not in effect on the host."),
    "open": ("stig-open", "STIG rule not yet addressed on {target}: {id}",
             "No decision in stig.toml covers this rule, and the host does not meet it."),
    "not-applicable": ("stig-review", "STIG rule marked not applicable fails on {target}: {id}",
                       "stig.toml calls this rule not applicable, but the scanner evaluated it and it failed."),
}


def _scan_entries(sources: Sources, evidence: RunEvidence, stig: StigCatalog) -> list[_Entry]:
    scan = evidence.scan
    entries = []
    for t in triage(scan, stig, sources.stig):
        if t.result == "fail" and _decision_class(t.decision) != "deviation":
            kind, title, statement = _SCAN_TITLES[_decision_class(t.decision)]
            entries.append(_scan_entry(sources, stig, t, kind, title.format(target=scan.target, id=t.stig_id), statement))
        elif t.result in UNEVALUATED:
            title = f"STIG rule not evaluated on {scan.target}: {t.stig_id} ({t.result})"
            entries.append(_scan_entry(sources, stig, t, "stig-unevaluated", title,
                                       "The scanner could not decide this rule; its state on the host is unknown."))
    order = ("stig-regression", "stig-open", "stig-review", "stig-unevaluated")
    return sorted(entries, key=lambda e: order.index(e.key[0]))


def _scan_entry(sources: Sources, stig: StigCatalog, t: TriagedResult, kind: str, title: str, statement: str) -> _Entry:
    rules = [t.rule] if t.rule else []
    return _Entry(
        key=(kind, t.stig_id),
        title=title,
        description=t.rule.title if t.rule else f"{t.stig_id} is not a rule in {stig.benchmark.release}.",
        statement=statement,
        props=_rule_props(rules, stig, sources.stig.component) if rules else (prop("stig-id", t.stig_id),),
        origin="stig-scan",
        remarks=_rule_line(t.rule) if t.rule else "",
    )


def _unverified_entry(sources: Sources, stig: StigCatalog) -> _Entry:
    decisions = sources.stig
    deviated = sum(len(d.rules) for d in decisions.deviations)
    not_applicable = sum(len(n.rules) for n in decisions.not_applicable)
    total = len(stig.benchmark.rules)
    rest = total - len(decisions.applied) - deviated - not_applicable
    return _Entry(
        key=("stig-unverified",),
        title="Host STIG baseline not verified by a scan",
        description=(
            f"The STIG role applies {len(decisions.applied)} of the {total} rules in "
            f"{stig.benchmark.title} {stig.benchmark.release}; "
            f"{_count(deviated, 'is a documented deviation', 'are documented deviations')} and "
            f"{_count(not_applicable, 'is not applicable', 'are not applicable')}. "
            "No scan results were supplied, so none of this is verified on a host, "
            f"and the remaining {rest} rules are unassessed."
        ),
        statement="Host hardening is configured as code but not yet shown to be in effect.",
        props=(prop("component", decisions.component),),
        origin="stig-scan",
        remediation=(
            f"Run {decisions.role} with its scan enabled, convert the results to a checklist with the "
            "MITRE SAF CLI, and pass the XCCDF results to the generator (--xccdf)."
        ),
    )


def _deviation_entries(sources: Sources, evidence: RunEvidence, stig: StigCatalog) -> list[_Entry]:
    scanned = {t.stig_id: t.result for t in triage(evidence.scan, stig, sources.stig)} if evidence.scan else {}
    entries = []
    for deviation in sources.stig.deviations:
        rules = [stig.rule(r) for r in deviation.rules]
        lines = [_rule_line(r) for r in rules]
        lines += [f"Scan of {evidence.scan.target}: {r} {scanned[r]}." for r in deviation.rules if r in scanned]
        entries.append(_Entry(
            key=("stig-deviation", deviation.key),
            title=f"STIG deviation: {deviation.title}",
            description=deviation.justification,
            statement=f"{_count(len(rules), 'STIG rule is', 'STIG rules are')} not met by design: "
                      + ", ".join(deviation.rules) + ".",
            status="deviation-requested",
            props=_rule_props(rules, stig, sources.stig.component),
            remarks="\n".join(lines),
            mitigation=deviation.mitigation,
            remediation=deviation.plan,
        ))
    return entries


# ---------------------------------------------------------------- implementation
def _implementation_entries(sources: Sources) -> list[_Entry]:
    return [
        _Entry(
            key=("implementation", control.id, c.component),
            title=f"{control.id.upper()} ({sources.system.component(c.component).title}): {c.status}",
            description=c.plan,
            statement=f"Stated in the SSP as {c.status}: {c.statement}",
            props=(
                *_related([control.id]),
                prop("component", c.component),
                prop("implementation-status", c.status),
                *((prop("milestone", c.milestone),) if c.milestone else ()),
                *(prop("planned-evidence", p) for p in c.planned_evidence),
            ),
            remediation=c.plan,
        )
        for control in sources.controls
        for c in control.contributions
        if c.status != "implemented"
    ]
