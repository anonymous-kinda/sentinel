"""Assessment results and POA&M, generated from CI evidence (the ARMOR pattern).

JUnit XML, harness JSON and XCCDF results go in; OSCAL comes out. A failed
check becomes a finding and a POA&M item; so does a check the SSP cites that
the run does not contain. Planned work and STIG deviations are POA&M items
too, so the POA&M is the whole list of what is not yet true.
"""

import dataclasses
import datetime as dt
import pathlib

import pytest

from compliance.assessment import build_assessment_results, build_poam
from compliance.evidence import collect
from compliance.inputs import read_harness, read_junit, read_xccdf
from compliance.oscal_common import NS, stable_uuid
from compliance.sources import load_sources
from compliance.stig import load_stig_catalog

DATA = pathlib.Path(__file__).parent / "data"
ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def sources():
    return load_sources(DATA / "sources")


@pytest.fixture(scope="module")
def stig(sources):
    return load_stig_catalog(ROOT, sources.stig)


@pytest.fixture(scope="module")
def run():
    return read_junit(DATA / "junit_mixed.xml")


@pytest.fixture(scope="module")
def evidence(sources, run):
    return collect(sources, run, harness=read_harness(DATA / "harness"), scan=None)


def props(node, name):
    return [p["value"] for p in node.get("props", []) if p["name"] == name and p["ns"] == NS]


def items_by_title(poam):
    return {i["title"]: i for i in poam["plan-of-action-and-milestones"]["poam-items"]}


def item_uuids(poam):
    return {i["title"]: i["uuid"] for i in poam["plan-of-action-and-milestones"]["poam-items"]}


def risk_of(poam, item):
    (ref,) = item["related-risks"]
    return next(r for r in poam["plan-of-action-and-milestones"]["risks"] if r["uuid"] == ref["risk-uuid"])


# ------------------------------------------------------------ assessment results
def test_results_span_the_run_and_review_every_control(sources, evidence, stig):
    ar = build_assessment_results(sources, evidence, stig)["assessment-results"]
    assert ar["import-ap"] == {"href": "trestle://assessment-plans/sentinel/assessment-plan.json"}
    (result,) = ar["results"]
    assert result["start"] == "2026-09-24T06:04:17Z"
    assert result["end"] == "2026-09-24T06:04:20Z"
    assert [c["control-id"] for c in result["reviewed-controls"]["control-selections"][0]["include-controls"]] == [
        "si-10", "au-9", "sc-13"
    ]
    assert ar["metadata"]["last-modified"] == "2026-09-24T06:04:20Z"


def test_one_observation_per_control_with_automated_evidence(sources, evidence, stig):
    (result,) = build_assessment_results(sources, evidence, stig)["assessment-results"]["results"]
    titles = [o["title"] for o in result["observations"]]
    assert titles == ["SI-10: automated evidence", "AU-9: automated evidence"]
    si10 = result["observations"][0]
    assert si10["methods"] == ["TEST"] and si10["types"] == ["control-objective"]
    assert si10["collected"] == "2026-09-24T06:04:17Z"
    assert si10["description"] == "2 of 2 cited checks passed. The SSP states SI-10 as implemented."
    assert props(si10, "implementation-status") == ["implemented"]
    assert [e["description"] for e in si10["relevant-evidence"]] == [
        "tests/test_cdm_codec.py::test_wrong_messages_are_rejected_with_a_named_reason: 2 cases passed",
        "tests/test_cdm_codec.py::test_absent_covariance_degrades_to_geometry_only: 1 case passed",
    ]
    assert props(si10["relevant-evidence"][0], "result") == ["passed"]
    assert si10["subjects"] == [{"subject-uuid": stable_uuid("component", "node"), "type": "component"}]
    assert si10["origins"] == [{"actors": [{"type": "tool", "actor-uuid": stable_uuid("assessment", "ladder")}]}]


def test_harness_evidence_is_attributed_to_the_harness(sources, evidence, stig):
    (result,) = build_assessment_results(sources, evidence, stig)["assessment-results"]["results"]
    au9 = result["observations"][1]
    actors = [a["actor-uuid"] for o in au9["origins"] for a in o["actors"]]
    assert actors == [stable_uuid("assessment", "ladder"), stable_uuid("assessment", "harness")]
    assert au9["description"] == "2 of 3 cited checks failed. The SSP states AU-9 as partial."
    assert "denied: all assertions passed" in au9["relevant-evidence"][2]["description"]


def test_failures_become_findings_against_the_control_objective(sources, evidence, stig):
    (result,) = build_assessment_results(sources, evidence, stig)["assessment-results"]["results"]
    (finding,) = result["findings"]
    assert finding["title"] == "AU-9 not satisfied"
    assert finding["target"] == {
        "type": "objective-id",
        "target-id": "au-9_obj",
        "status": {"state": "not-satisfied", "reason": "fail"},
        "implementation-status": {"state": "partial"},
    }
    assert finding["related-observations"] == [{"observation-uuid": result["observations"][1]["uuid"]}]
    assert "test_editing_a_line_is_detected_at_that_line" in finding["description"]


def test_missing_evidence_alone_is_not_satisfied_for_another_reason(sources, run, stig):
    control = sources.controls[0]
    renamed = dataclasses.replace(control.contributions[0], tests=("tests/test_cdm_codec.py::test_renamed",))
    changed = dataclasses.replace(sources, controls=(dataclasses.replace(control, contributions=(renamed,)),))
    evidence = collect(changed, run, harness=None, scan=None)
    (result,) = build_assessment_results(changed, evidence, stig)["assessment-results"]["results"]
    (finding,) = [f for f in result["findings"] if f["title"] == "SI-10 not satisfied"]
    assert finding["target"]["status"] == {"state": "not-satisfied", "reason": "other"}
    assert "not in this run" in finding["description"]


def test_without_harness_results_the_observation_says_so(sources, run, stig):
    evidence = collect(sources, run, harness=None, scan=None)
    (result,) = build_assessment_results(sources, evidence, stig)["assessment-results"]["results"]
    au9 = result["observations"][1]
    assert au9["description"] == "2 of 2 cited checks failed; 1 not supplied to this run. The SSP states AU-9 as partial."
    assert "denied: harness results not supplied" in au9["relevant-evidence"][2]["description"]


def test_a_scan_is_summarised_as_one_observation_of_the_hardened_component(sources, run, stig):
    evidence = collect(sources, run, harness=None, scan=read_xccdf(DATA / "xccdf_results.xml"))
    (result,) = build_assessment_results(sources, evidence, stig)["assessment-results"]["results"]
    scan = result["observations"][-1]
    assert scan["title"] == "STIG scan of sentinel-hub"
    assert scan["subjects"] == [{"subject-uuid": stable_uuid("component", "host"), "type": "component"}]
    assert scan["description"] == (
        "6 rules evaluated with xccdf_mil.disa.stig_profile_MAC-2_Sensitive: 1 pass, 3 fail "
        "(1 applied rule, 1 documented deviation, 1 not yet addressed), 1 not applicable, 1 not evaluated."
    )


def test_results_identity_is_stable_for_the_same_evidence(sources, evidence, stig):
    first = build_assessment_results(sources, evidence, stig)
    assert first == build_assessment_results(sources, evidence, stig)


# ----------------------------------------------------------------------- POA&M
def test_poam_points_at_the_ssp_and_the_system(sources, evidence, stig):
    poam = build_poam(sources, evidence, stig)["plan-of-action-and-milestones"]
    assert poam["import-ssp"] == {"href": "trestle://system-security-plans/sentinel/system-security-plan.json"}
    assert poam["system-id"] == {"identifier-type": "https://ietf.org/rfc/rfc4122", "id": stable_uuid("system", "sentinel")}


def test_every_failing_test_is_an_open_item_linked_to_its_controls(sources, evidence, stig):
    poam = build_poam(sources, evidence, stig)
    items = items_by_title(poam)
    item = items["Failing test: tests.ai.test_audit::test_editing_a_line_is_detected_at_that_line"]
    assert props(item, "related-control") == ["au-9"]
    assert "AssertionError: assert True is False" in item["description"]
    assert risk_of(poam, item)["status"] == "open"
    assert "Failing test: tests.ai.test_audit::test_deleting_a_line_is_detected" in items


def test_every_contribution_short_of_implemented_is_an_item_with_its_plan(sources, evidence, stig):
    poam = build_poam(sources, evidence, stig)
    items = items_by_title(poam)
    item = items["AU-9 (Sentinel node software): partial"]
    assert item["description"] == "Anchor the chain head off-node so tail truncation is detectable."
    assert props(item, "milestone") == ["M5"]
    assert props(item, "related-control") == ["au-9"]
    risk = risk_of(poam, item)
    assert risk["status"] == "open"
    assert risk["remediations"][0]["lifecycle"] == "planned"
    assert "AU-9 (Node host baseline): planned" in items
    assert props(items["SC-13 (Sentinel node software): planned"], "planned-evidence") == ["docs/supply-chain.md"]


def test_a_stig_deviation_is_requested_not_approved_and_mapped_by_disa(sources, evidence, stig):
    poam = build_poam(sources, evidence, stig)
    item = items_by_title(poam)["STIG deviation: Login banner text is not the DoD notice"]
    assert props(item, "stig-id") == ["UBTU-24-200640"]
    assert props(item, "related-control") == ["ac-8"]
    assert props(item, "stig-severity") == ["medium"]
    assert "UBTU-24-200640 (V-270691, SV-270691r1066562_rule, CAT II)" in item["remarks"]
    risk = risk_of(poam, item)
    assert risk["status"] == "deviation-requested"
    assert risk["mitigating-factors"][0]["description"] == "The banner mechanism is configured; only the text differs."


def test_without_a_scan_the_host_baseline_is_an_open_item(sources, evidence, stig):
    items = items_by_title(build_poam(sources, evidence, stig))
    item = items["Host STIG baseline not verified by a scan"]
    assert item["description"].startswith(
        "The STIG role applies 2 of the 194 rules in Canonical Ubuntu 24.04 LTS Security Technical "
        "Implementation Guide V1R6; 1 is a documented deviation and 1 is not applicable."
    )


def test_scan_results_are_triaged_against_the_stig_decisions(sources, run, stig):
    evidence = collect(sources, run, harness=None, scan=read_xccdf(DATA / "xccdf_results.xml"))
    poam = build_poam(sources, evidence, stig)
    items = items_by_title(poam)
    assert "Host STIG baseline not verified by a scan" not in items
    regression = items["Applied STIG rule fails on sentinel-hub: UBTU-24-100820"]
    assert props(regression, "stig-severity") == ["medium"]
    assert "STIG rule not yet addressed on sentinel-hub: UBTU-24-300027" in items
    assert "STIG rule not evaluated on sentinel-hub: UBTU-24-600070 (error)" in items
    deviation = items["STIG deviation: Login banner text is not the DoD notice"]
    assert "Scan of sentinel-hub: UBTU-24-200640 fail." in deviation["remarks"]
    assert not any("UBTU-24-100030" in title or "UBTU-24-200020" in title for title in items)


def test_item_identity_survives_a_new_run(sources, stig, run):
    later = dataclasses.replace(run, started=run.started + dt.timedelta(days=1))
    first = build_poam(sources, collect(sources, run, None, None), stig)
    second = build_poam(sources, collect(sources, later, None, None), stig)
    assert item_uuids(first) == item_uuids(second)
    assert first["plan-of-action-and-milestones"]["uuid"] != second["plan-of-action-and-milestones"]["uuid"]


def test_items_are_ordered_most_urgent_first(sources, run, stig):
    evidence = collect(sources, run, harness=None, scan=read_xccdf(DATA / "xccdf_results.xml"))
    titles = list(items_by_title(build_poam(sources, evidence, stig)))
    kinds = [t.split(":")[0] for t in titles]
    assert kinds[:2] == ["Failing test", "Failing test"]
    assert titles.index("Applied STIG rule fails on sentinel-hub: UBTU-24-100820") < titles.index(
        "AU-9 (Sentinel node software): partial"
    )
    assert titles[-1] == "STIG deviation: Login banner text is not the DoD notice"
