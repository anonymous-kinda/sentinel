"""Authored sources: system.toml, controls.toml, stig.toml.

These three files are the only hand-edited inputs to the OSCAL package.
Loading them enforces the rules that keep the SSP honest:

  * a contribution is `implemented` only when automated evidence (tests, a
    DDIL harness scenario or a CI job) stands behind it;
  * `partial` and `planned` contributions carry a plan, which becomes a
    POA&M item;
  * an unknown key is an error, so a typo cannot silently drop evidence.

Every violation raises SourceError: generating from a misstated source would
publish a wrong document.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import pathlib
import re
import tomllib
from typing import Any

STATES = ("implemented", "partial", "planned")
COMPONENT_TYPES = frozenset(
    {"this-system", "system", "interconnection", "software", "hardware", "service", "policy", "physical",
     "process-procedure", "plan", "guidance", "standard", "validation", "network"}
)
OPERATIONAL_STATES = frozenset({"operational", "under-development", "under-major-modification", "disposition", "other"})

# The evidence readers the generator has: JUnit XML, harness JSON, XCCDF results.
ASSESSMENT_KEYS = ("ladder", "harness", "stig-scan")

_CONTROL_ID = re.compile(r"^[a-z]{2}-\d+(\.\d+)?$")
_TEST_CITATION = re.compile(r"^tests/[\w/]+\.py(::\w+)*$")
_CI_CITATION = re.compile(r"^[\w.-]+\.ya?ml#[\w-]+$")
_STIG_ID = re.compile(r"^UBTU-24-\d{6}$")


class SourceError(ValueError):
    """An authored source that would misstate the system. Nothing is generated from it."""


# ------------------------------------------------------------------ model
@dataclasses.dataclass(frozen=True)
class Contribution:
    component: str
    status: str
    statement: str
    tests: tuple[str, ...] = ()
    harness: tuple[str, ...] = ()
    ci: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    planned_evidence: tuple[str, ...] = ()
    plan: str = ""
    milestone: str = ""

    @property
    def automated(self) -> bool:
        return bool(self.tests or self.harness or self.ci)


@dataclasses.dataclass(frozen=True)
class Control:
    id: str
    rationale: str
    contributions: tuple[Contribution, ...]
    params: dict[str, str] = dataclasses.field(default_factory=dict)

    @property
    def status(self) -> str:
        states = {c.status for c in self.contributions}
        if len(states) == 1:
            return states.pop()
        return "partial"


@dataclasses.dataclass(frozen=True)
class Component:
    key: str
    type: str
    title: str
    description: str
    state: str


@dataclasses.dataclass(frozen=True)
class Party:
    key: str
    type: str
    name: str
    roles: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class User:
    key: str
    title: str
    description: str
    roles: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class InformationType:
    title: str
    description: str
    confidentiality: str
    integrity: str
    availability: str


@dataclasses.dataclass(frozen=True)
class Assessment:
    key: str
    title: str
    description: str
    ci: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Document:
    version: str
    last_modified: dt.datetime


@dataclasses.dataclass(frozen=True)
class System:
    document: Document
    name: str
    short_name: str
    description: str
    state: str
    state_remarks: str
    authorization_boundary: str
    impact: dict[str, str]
    information_types: tuple[InformationType, ...]
    roles: tuple[tuple[str, str], ...]
    parties: tuple[Party, ...]
    users: tuple[User, ...]
    components: tuple[Component, ...]
    assessments: tuple[Assessment, ...]
    network_architecture: str = ""
    data_flow: str = ""

    def component(self, key: str) -> Component:
        return next(c for c in self.components if c.key == key)

    def assessment(self, key: str) -> Assessment:
        return next(a for a in self.assessments if a.key == key)


@dataclasses.dataclass(frozen=True)
class NotApplicable:
    rules: tuple[str, ...]
    reason: str


@dataclasses.dataclass(frozen=True)
class Deviation:
    key: str
    title: str
    rules: tuple[str, ...]
    justification: str
    mitigation: str
    plan: str


@dataclasses.dataclass(frozen=True)
class StigDecisions:
    component: str  # the system component the STIG role hardens
    xccdf: str
    cci_list: str
    role: str
    applied: tuple[str, ...]
    not_applicable: tuple[NotApplicable, ...]
    deviations: tuple[Deviation, ...]

    def decided(self) -> tuple[str, ...]:
        """Every rule stig.toml takes a position on, in file order (duplicates kept, for checking)."""
        groups = [self.applied, *(n.rules for n in self.not_applicable), *(d.rules for d in self.deviations)]
        return tuple(rule for group in groups for rule in group)

    def decision(self, stig_id: str) -> str | None:
        """'applied', 'not-applicable', a deviation key, or None if never decided."""
        if stig_id in self.applied:
            return "applied"
        if any(stig_id in n.rules for n in self.not_applicable):
            return "not-applicable"
        return next((d.key for d in self.deviations if stig_id in d.rules), None)


@dataclasses.dataclass(frozen=True)
class Sources:
    system: System
    controls: tuple[Control, ...]
    stig: StigDecisions


# ---------------------------------------------------------------- loading
def load_sources(directory: pathlib.Path) -> Sources:
    system = _load_system(_read(directory / "system.toml"))
    controls = _load_controls(_read(directory / "controls.toml"), {c.key for c in system.components})
    stig = _load_stig(_read(directory / "stig.toml"), {c.key for c in system.components})
    return Sources(system, controls, stig)


def _read(path: pathlib.Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SourceError(f"{path.name}: {exc}") from exc


def _keys(table: dict, where: str, required: set[str], optional: set[str] = frozenset()) -> None:
    unknown = set(table) - required - optional
    if unknown:
        raise SourceError(f"{where}: unknown key '{sorted(unknown)[0]}'")
    missing = required - set(table)
    if missing:
        raise SourceError(f"{where}: missing key '{sorted(missing)[0]}'")
    for key in required:
        if isinstance(table[key], str) and not table[key].strip():
            raise SourceError(f"{where}: {key} is empty")


# ---------------------------------------------------------------- system
def _load_system(raw: dict) -> System:
    _keys(
        raw, "system.toml",
        {"document", "system", "information_type", "role", "party", "component", "assessment"}, {"user"},
    )
    doc, sysd = raw["document"], raw["system"]
    _keys(doc, "system.toml [document]", {"version", "last_modified"})
    _keys(
        sysd, "system.toml [system]",
        {"name", "short_name", "description", "state", "state_remarks", "authorization_boundary", "impact"},
        {"network_architecture", "data_flow"},
    )
    if sysd["state"] not in OPERATIONAL_STATES:
        raise SourceError(f"system.toml: state '{sysd['state']}' is not an OSCAL operational state")
    if not isinstance(doc["last_modified"], dt.datetime) or doc["last_modified"].tzinfo is None:
        raise SourceError("system.toml: last_modified must be a TOML datetime with a UTC offset")
    components = tuple(_component(c) for c in raw["component"])
    if len({c.key for c in components}) != len(components):
        raise SourceError("system.toml: duplicate component key")
    return System(
        document=Document(str(doc["version"]), doc["last_modified"]),
        name=sysd["name"], short_name=sysd["short_name"], description=sysd["description"],
        state=sysd["state"], state_remarks=sysd["state_remarks"],
        authorization_boundary=sysd["authorization_boundary"],
        network_architecture=sysd.get("network_architecture", ""), data_flow=sysd.get("data_flow", ""),
        impact=dict(sysd["impact"]),
        information_types=tuple(InformationType(**i) for i in raw["information_type"]),
        roles=tuple((r["id"], r["title"]) for r in raw["role"]),
        parties=tuple(Party(p["key"], p["type"], p["name"], tuple(p["roles"])) for p in raw["party"]),
        users=tuple(User(u["key"], u["title"], u["description"], tuple(u["roles"])) for u in raw.get("user", [])),
        components=components,
        assessments=_assessments(raw["assessment"]),
    )


def _assessments(raw: list[dict]) -> tuple[Assessment, ...]:
    methods = []
    for table in raw:
        _keys(table, f"assessment {table.get('key')}", {"key", "title", "description"}, {"ci"})
        methods.append(Assessment(table["key"], table["title"], table["description"], tuple(table.get("ci", ()))))
    if sorted(m.key for m in methods) != sorted(ASSESSMENT_KEYS):
        raise SourceError(f"system.toml: assessment keys must be exactly {', '.join(ASSESSMENT_KEYS)}")
    return tuple(methods)


def _component(raw: dict) -> Component:
    _keys(raw, f"component {raw.get('key')}", {"key", "type", "title", "description", "state"})
    if raw["type"] not in COMPONENT_TYPES:
        raise SourceError(f"component {raw['key']}: type '{raw['type']}' is not an OSCAL component type")
    if raw["state"] not in OPERATIONAL_STATES:
        raise SourceError(f"component {raw['key']}: state '{raw['state']}' is not an OSCAL operational state")
    return Component(**raw)


# -------------------------------------------------------------- controls
def _load_controls(raw: dict, components: set[str]) -> tuple[Control, ...]:
    _keys(raw, "controls.toml", {"control"})
    controls: list[Control] = []
    for table in raw["control"]:
        control = _control(table, components)
        if any(c.id == control.id for c in controls):
            raise SourceError(f"controls.toml: duplicate control {control.id}")
        controls.append(control)
    return tuple(controls)


def _control(raw: dict, components: set[str]) -> Control:
    cid = raw.get("id", "")
    if not _CONTROL_ID.match(cid):
        raise SourceError(f"controls.toml: control id '{cid}' is not an 800-53 id such as 'si-10' or 'ac-2.1'")
    _keys(raw, cid, {"id", "rationale", "by"}, {"params"})
    return Control(
        id=cid,
        rationale=raw["rationale"],
        contributions=tuple(_contribution(cid, b, components) for b in raw["by"]),
        params=dict(raw.get("params", {})),
    )


_CONTRIBUTION_REQUIRED = {"component", "status", "statement"}
_CONTRIBUTION_OPTIONAL = {"tests", "harness", "ci", "files", "planned_evidence", "plan", "milestone"}


def _contribution(cid: str, raw: dict, components: set[str]) -> Contribution:
    where = f"{cid} ({raw.get('component')})"
    _keys(raw, where, _CONTRIBUTION_REQUIRED, _CONTRIBUTION_OPTIONAL)
    if raw["component"] not in components:
        raise SourceError(f"{cid}: unknown component '{raw['component']}'")
    if raw["status"] not in STATES:
        raise SourceError(f"{where}: status '{raw['status']}' is not one of {', '.join(STATES)}")
    contribution = Contribution(**{k: tuple(v) if isinstance(v, list) else v for k, v in raw.items()})
    for test in contribution.tests:
        if not _TEST_CITATION.match(test):
            raise SourceError(f"{where}: test citation '{test}' is not a pytest node id like tests/x.py::test_y")
    for job in contribution.ci:
        if not _CI_CITATION.match(job):
            raise SourceError(f"{where}: CI citation '{job}' is not workflow.yml#job")
    if contribution.status == "implemented" and not contribution.automated:
        raise SourceError(f"{where}: implemented needs automated evidence (tests, harness or ci)")
    if contribution.status != "implemented" and not contribution.plan.strip():
        raise SourceError(f"{where}: a {contribution.status} contribution needs a plan")
    return contribution


# ------------------------------------------------------------------ STIG
def _load_stig(raw: dict, components: set[str]) -> StigDecisions:
    _keys(raw, "stig.toml", {"benchmark", "applied"}, {"not_applicable", "deviation"})
    bench = raw["benchmark"]
    _keys(bench, "stig.toml [benchmark]", {"component", "xccdf", "cci_list", "role"})
    if bench["component"] not in components:
        raise SourceError(f"stig.toml: unknown component '{bench['component']}'")
    decisions = StigDecisions(
        component=bench["component"], xccdf=bench["xccdf"], cci_list=bench["cci_list"], role=bench["role"],
        applied=tuple(raw["applied"]),
        not_applicable=tuple(NotApplicable(tuple(n["rules"]), n["reason"]) for n in raw.get("not_applicable", [])),
        deviations=tuple(_deviation(d) for d in raw.get("deviation", [])),
    )
    _check_rule_ids(decisions)
    return decisions


def _deviation(raw: dict) -> Deviation:
    _keys(raw, f"deviation {raw.get('key')}", {"key", "title", "rules", "justification", "mitigation", "plan"})
    return Deviation(**{k: tuple(v) if isinstance(v, list) else v for k, v in raw.items()})


def _check_rule_ids(decisions: StigDecisions) -> None:
    seen: set[str] = set()
    for rule in decisions.decided():
        if not _STIG_ID.match(rule):
            raise SourceError(f"stig.toml: STIG id '{rule}' is not a Ubuntu 24.04 STIG id (UBTU-24-NNNNNN)")
        if rule in seen:
            raise SourceError(f"stig.toml: {rule} appears in more than one decision")
        seen.add(rule)
