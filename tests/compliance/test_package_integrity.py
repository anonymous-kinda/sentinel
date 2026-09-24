"""The real compliance package, reconciled against its ground truth.

The SSP is checked the way ARMOR checks a quarantine list: against the source
it claims to describe. The NIST catalog decides which controls, objectives and
parameters exist; the repository decides which evidence exists; DISA's files
decide which STIG rules exist; the sources decide what the committed OSCAL
documents say.
"""

import hashlib
import json
import pathlib
import re

import pytest

from compliance import authored, oscal_common
from compliance.citations import unresolved
from compliance.sources import load_sources
from compliance.stig import load_benchmark

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPLIANCE = ROOT / "compliance"
CATALOG = COMPLIANCE / "vendor" / "nist" / "NIST_SP-800-53_rev5_catalog-min.json"


@pytest.fixture(scope="module")
def sources():
    return load_sources(COMPLIANCE / "sources")


@pytest.fixture(scope="module")
def catalog():
    controls = {}

    def walk(nodes):
        for control in nodes:
            controls[control["id"]] = control
            walk(control.get("controls", []))

    for group in json.loads(CATALOG.read_text())["catalog"]["groups"]:
        walk(group.get("controls", []))
    return controls


@pytest.mark.parametrize("directory", ["nist", "disa"])
def test_vendored_upstream_files_are_unmodified(directory):
    folder = COMPLIANCE / "vendor" / directory
    for line in (folder / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name


def test_profile_controls_objectives_and_parameters_exist_in_the_catalog(sources, catalog):
    for control in sources.controls:
        assert control.id in catalog, f"{control.id} is not a SP 800-53 Rev 5 control"
        entry = catalog[control.id]
        assert any(p.get("id") == f"{control.id}_obj" for p in entry.get("parts", [])), control.id
        params = {p["id"] for p in entry.get("params", [])}
        assert set(control.params) <= params, f"{control.id}: unknown parameters {set(control.params) - params}"


def test_no_withdrawn_control_is_selected(sources, catalog):
    withdrawn = [
        c.id for c in sources.controls
        if any(p["name"] == "status" and p["value"] == "withdrawn" for p in catalog[c.id].get("props", []))
    ]
    assert withdrawn == []


def test_every_citation_resolves(sources):
    assert unresolved(sources, ROOT) == []


AUTHORED = {
    oscal_common.PROFILE: authored.build_profile,
    oscal_common.COMPONENT_DEFINITION: authored.build_component_definition,
    oscal_common.SSP: authored.build_ssp,
    oscal_common.ASSESSMENT_PLAN: authored.build_assessment_plan,
}


@pytest.mark.parametrize("relative", sorted(AUTHORED))
def test_committed_documents_are_what_the_sources_generate(sources, relative):
    committed = json.loads((COMPLIANCE / "oscal" / relative).read_text())
    assert committed == AUTHORED[relative](sources), (
        f"{relative} is stale or was edited by hand: run `make compliance` and commit the result"
    )


def test_stig_counts_stated_in_the_ssp_are_the_decisions(sources):
    stig = sources.stig
    host_cm6 = next(c for c in sources.controls if c.id == "cm-6").contributions[1].statement
    applied, deviations, not_applicable = map(
        int, re.search(r"applies (\d+) rules.*?records (\d+)\s+documented deviations and (\d+) rules", host_cm6, re.DOTALL).groups()
    )
    assert applied == len(stig.applied)
    assert deviations == sum(len(d.rules) for d in stig.deviations)
    assert not_applicable == sum(len(n.rules) for n in stig.not_applicable)


def test_the_compliance_doc_states_the_current_counts(sources):
    """docs/compliance.md is prose, but its numbers must be the sources' numbers."""
    doc = (ROOT / "docs" / "compliance.md").read_text()
    contributions = [c for control in sources.controls for c in control.contributions]
    expected = {
        "controls": len(sources.controls),
        "implemented controls": sum(c.status == "implemented" for c in sources.controls),
        "partial controls": sum(c.status == "partial" for c in sources.controls),
        "planned controls": sum(c.status == "planned" for c in sources.controls),
        "contributions": len(contributions),
        "implemented contributions": sum(c.status == "implemented" for c in contributions),
        "partial contributions": sum(c.status == "partial" for c in contributions),
        "planned contributions": sum(c.status == "planned" for c in contributions),
        "applied rules": len(sources.stig.applied),
        "deviating rules": sum(len(d.rules) for d in sources.stig.deviations),
        "not applicable rules": sum(len(n.rules) for n in sources.stig.not_applicable),
        "deviations": len(sources.stig.deviations),
        "unassessed rules": len(load_benchmark(ROOT / sources.stig.xccdf).rules) - len(sources.stig.decided()),
    }
    stated = {key: int(value) for value, key in re.findall(r"\*\*(\d+)\*\* ([a-z ]+?)(?=[,.;:)]|$)", doc, re.MULTILINE)}
    assert {k: stated.get(k) for k in expected} == expected


def test_no_authorization_is_claimed(sources):
    ssp = authored.build_ssp(sources)["system-security-plan"]["system-characteristics"]
    assert "date-authorized" not in ssp
    assert ssp["status"]["state"] != "operational"
    assert "No authorization to operate has been sought or granted" in ssp["status"]["remarks"]


def test_committed_poam_never_approves_a_deviation():
    poam = json.loads((COMPLIANCE / "oscal" / oscal_common.POAM).read_text())["plan-of-action-and-milestones"]
    assert {r["status"] for r in poam["risks"]} <= {"open", "deviation-requested"}
