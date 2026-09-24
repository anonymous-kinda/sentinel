"""Profile, component definition, SSP and assessment plan, built from the sources.

These documents are generated, never hand-edited, so they must be a pure
function of the sources: the same input gives byte-identical output, and
identifiers stay stable while content changes.
"""

import dataclasses
import pathlib
import uuid

import pytest

from compliance.authored import (
    build_assessment_plan,
    build_component_definition,
    build_profile,
    build_ssp,
)
from compliance.oscal_common import NS, stable_uuid
from compliance.sources import load_sources

SOURCES = pathlib.Path(__file__).parent / "data" / "sources"


@pytest.fixture(scope="module")
def sources():
    return load_sources(SOURCES)


def props(node, name):
    return [p["value"] for p in node.get("props", []) if p["name"] == name and p["ns"] == NS]


# -------------------------------------------------------------------- profile
def test_profile_selects_exactly_the_tailored_controls(sources):
    profile = build_profile(sources)["profile"]
    (imported,) = profile["imports"]
    assert imported["href"] == "trestle://catalogs/nist-800-53-rev5/catalog.json"
    assert imported["include-controls"] == [{"with-ids": ["si-10", "au-9", "sc-13"]}]
    assert profile["merge"] == {"as-is": True}


def test_profile_sets_the_authored_parameters(sources):
    modify = build_profile(sources)["profile"]["modify"]
    assert modify["set-parameters"] == [
        {"param-id": "si-10_odp", "values": ["Conjunction Data Messages submitted for ingest"]}
    ]


def test_profile_records_why_each_control_was_selected(sources):
    alters = {a["control-id"]: a for a in build_profile(sources)["profile"]["modify"]["alters"]}
    (add,) = alters["si-10"]["adds"]
    assert props(add, "tailoring-rationale") == ["CDMs arrive from outside the boundary."]


# --------------------------------------------------------- component definition
def test_component_definition_has_one_entry_per_component(sources):
    components = build_component_definition(sources)["component-definition"]["components"]
    assert [(c["title"], c["type"]) for c in components] == [
        ("Sentinel node software", "software"),
        ("Node host baseline", "software"),
    ]
    assert components[0]["uuid"] == stable_uuid("component", "node")


def test_component_requirements_carry_status_and_evidence(sources):
    node = build_component_definition(sources)["component-definition"]["components"][0]
    (implementation,) = node["control-implementations"]
    assert implementation["source"] == "trestle://profiles/sentinel/profile.json"
    by_control = {r["control-id"]: r for r in implementation["implemented-requirements"]}
    assert list(by_control) == ["si-10", "au-9", "sc-13"]
    si10 = by_control["si-10"]
    assert si10["description"] == "Wrong CDMs are quarantined; incomplete CDMs degrade."
    assert props(si10, "implementation-status") == ["implemented"]
    assert props(si10, "evidence-test") == [
        "tests/test_cdm_codec.py::test_wrong_messages_are_rejected_with_a_named_reason",
        "tests/test_cdm_codec.py::test_absent_covariance_degrades_to_geometry_only",
    ]
    assert props(si10, "evidence-file") == ["sentinel/cdm/validate.py"]
    assert "remarks" not in si10


def test_a_contribution_short_of_implemented_carries_its_plan(sources):
    node = build_component_definition(sources)["component-definition"]["components"][0]
    by_control = {r["control-id"]: r for r in node["control-implementations"][0]["implemented-requirements"]}
    au9 = by_control["au-9"]
    assert props(au9, "implementation-status") == ["partial"]
    assert props(au9, "evidence-harness") == ["denied"]
    assert props(au9, "milestone") == ["M5"]
    assert au9["remarks"] == "Plan: Anchor the chain head off-node so tail truncation is detectable."
    assert props(by_control["sc-13"], "planned-evidence") == ["docs/fips-provider.md"]


# ------------------------------------------------------------------------ SSP
def test_ssp_imports_the_profile_and_describes_the_system(sources):
    ssp = build_ssp(sources)["system-security-plan"]
    assert ssp["import-profile"] == {"href": "trestle://profiles/sentinel/profile.json"}
    chars = ssp["system-characteristics"]
    assert chars["system-name"] == "Sentinel"
    assert chars["status"] == {"state": "under-development", "remarks": "Draft. No authorization has been sought or granted."}
    assert chars["security-impact-level"] == {
        "security-objective-confidentiality": "fips-199-low",
        "security-objective-integrity": "fips-199-moderate",
        "security-objective-availability": "fips-199-moderate",
    }
    (info,) = chars["system-information"]["information-types"]
    assert info["integrity-impact"] == {"base": "fips-199-moderate"}


def test_ssp_components_share_identity_with_the_component_definition(sources):
    ssp_components = build_ssp(sources)["system-security-plan"]["system-implementation"]["components"]
    compdef_components = build_component_definition(sources)["component-definition"]["components"]
    assert [c["uuid"] for c in ssp_components] == [c["uuid"] for c in compdef_components]
    assert ssp_components[0]["status"] == {"state": "under-development"}


def test_ssp_states_each_components_part_of_each_control(sources):
    requirements = build_ssp(sources)["system-security-plan"]["control-implementation"]["implemented-requirements"]
    au9 = next(r for r in requirements if r["control-id"] == "au-9")
    assert props(au9, "implementation-status") == ["partial"]
    node, host = au9["by-components"]
    assert node["component-uuid"] == stable_uuid("component", "node")
    assert node["implementation-status"] == {
        "state": "partial",
        "remarks": "Anchor the chain head off-node so tail truncation is detectable.",
    }
    assert host["implementation-status"]["state"] == "planned"
    assert props(node, "evidence-test")[0] == "tests/ai/test_audit.py::test_editing_a_line_is_detected_at_that_line"
    assert au9["remarks"] == "Selected because: Decisions and AI interactions must be tamper-evident."


def test_ssp_names_roles_parties_and_users(sources):
    ssp = build_ssp(sources)["system-security-plan"]
    assert [r["id"] for r in ssp["metadata"]["roles"]] == ["maintainer", "operator"]
    (party,) = ssp["metadata"]["parties"]
    assert ssp["metadata"]["responsible-parties"] == [{"role-id": "maintainer", "party-uuids": [party["uuid"]]}]
    (user,) = ssp["system-implementation"]["users"]
    assert user["role-ids"] == ["operator"]


# ------------------------------------------------------------ assessment plan
def test_assessment_plan_reviews_every_profile_control(sources):
    plan = build_assessment_plan(sources)["assessment-plan"]
    assert plan["import-ssp"] == {"href": "trestle://system-security-plans/sentinel/system-security-plan.json"}
    assert plan["reviewed-controls"]["control-selections"] == [
        {"include-controls": [{"control-id": "si-10"}, {"control-id": "au-9"}, {"control-id": "sc-13"}]}
    ]


def test_assessment_plan_declares_one_tool_and_task_per_method(sources):
    plan = build_assessment_plan(sources)["assessment-plan"]
    tools = plan["assessment-assets"]["components"]
    assert [t["uuid"] for t in tools] == [stable_uuid("assessment", k) for k in ("ladder", "harness", "stig-scan")]
    (platform,) = plan["assessment-assets"]["assessment-platforms"]
    assert [u["component-uuid"] for u in platform["uses-components"]] == [t["uuid"] for t in tools]
    assert [t["title"] for t in plan["tasks"]] == ["Test ladder (pytest)", "DDIL harness", "OpenSCAP scan against the DISA STIG benchmark"]
    assert props(plan["tasks"][0], "evidence-ci") == ["ci.yml#python"]
    subjects = plan["assessment-subjects"][0]["include-subjects"]
    assert [s["subject-uuid"] for s in subjects] == [stable_uuid("component", "node"), stable_uuid("component", "host")]


# ------------------------------------------------------------- determinism
BUILDERS = [build_profile, build_component_definition, build_ssp, build_assessment_plan]


@pytest.mark.parametrize("build", BUILDERS)
def test_documents_are_a_pure_function_of_the_sources(sources, build):
    assert build(sources) == build(load_sources(SOURCES))


@pytest.mark.parametrize("build", BUILDERS)
def test_document_identity_follows_content(sources, build):
    (kind, document), = build(sources).items()
    control = dataclasses.replace(sources.controls[0], rationale="Changed.")
    changed = dataclasses.replace(sources, controls=(control, *sources.controls[1:]))
    (_, other), = build(changed).items()
    assert uuid.UUID(document["uuid"]).version == 5
    affected = build in (build_profile, build_ssp)
    assert (document["uuid"] != other["uuid"]) is affected


@pytest.mark.parametrize("build", BUILDERS)
def test_metadata_is_oscal_1_2_with_the_authored_version_and_time(sources, build):
    (_, document), = build(sources).items()
    metadata = document["metadata"]
    assert metadata["oscal-version"] == "1.2.1"
    assert metadata["version"] == "0.1.0"
    assert metadata["last-modified"] == "2026-09-23T00:00:00Z"
