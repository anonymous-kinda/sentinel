"""Authored sources: the only hand-edited inputs to the OSCAL package.

Loading enforces the honesty rules: a contribution is `implemented` only with
automated evidence behind it, anything less carries a plan, and a typo in a
key is an error rather than evidence silently dropped.
"""

import pathlib
import shutil

import pytest

from compliance.sources import SourceError, load_sources

SOURCES = pathlib.Path(__file__).parent / "data" / "sources"


def mutated(tmp_path: pathlib.Path, filename: str, old: str, new: str) -> pathlib.Path:
    target = tmp_path / "sources"
    shutil.copytree(SOURCES, target)
    path = target / filename
    text = path.read_text()
    assert old in text, f"fixture no longer contains {old!r}"
    path.write_text(text.replace(old, new, 1))
    return target


def test_system_and_components_load():
    sources = load_sources(SOURCES)
    assert sources.system.name == "Sentinel"
    assert [c.key for c in sources.system.components] == ["node", "host"]
    assert sources.system.document.version == "0.1.0"


def test_controls_keep_their_authored_order_and_evidence():
    controls = load_sources(SOURCES).controls
    assert [c.id for c in controls] == ["si-10", "au-9", "sc-13"]
    si10 = controls[0]
    assert si10.params == {"si-10_odp": "Conjunction Data Messages submitted for ingest"}
    (node,) = si10.contributions
    assert node.tests[0] == "tests/test_cdm_codec.py::test_wrong_messages_are_rejected_with_a_named_reason"
    assert node.files == ("sentinel/cdm/validate.py",)


@pytest.mark.parametrize(("control", "expected"), [("si-10", "implemented"), ("au-9", "partial"), ("sc-13", "planned")])
def test_overall_status_is_derived_from_the_contributions(control, expected):
    by_id = {c.id: c for c in load_sources(SOURCES).controls}
    assert by_id[control].status == expected


def test_assessment_methods_load_in_order():
    methods = load_sources(SOURCES).system.assessments
    assert [m.key for m in methods] == ["ladder", "harness", "stig-scan"]
    assert methods[0].ci == ("ci.yml#python",) and methods[2].ci == ()


def test_stig_decisions_load():
    stig = load_sources(SOURCES).stig
    assert stig.component == "host"
    assert stig.applied == ("UBTU-24-100030", "UBTU-24-100820")
    assert stig.not_applicable[0].rules == ("UBTU-24-200020",)
    assert stig.deviations[0].key == "login-banner" and stig.deviations[0].rules == ("UBTU-24-200640",)


@pytest.mark.parametrize(
    ("filename", "old", "new", "reason"),
    [
        ("controls.toml", 'files = ["sentinel/cdm/validate.py"]', 'status_note = "x"', "unknown key 'status_note'"),
        ("controls.toml", "tests = [\n    \"tests/test_cdm_codec.py::test_wrong", "test = [\n    \"tests/test_cdm_codec.py::test_wrong", "unknown key 'test'"),
        ("controls.toml", 'status = "partial"', 'status = "mostly"', "status 'mostly'"),
        ("controls.toml", 'plan = "Anchor the chain head off-node so tail truncation is detectable."\n', "", "needs a plan"),
        ("controls.toml", 'component = "host"', 'component = "cloud"', "unknown component 'cloud'"),
        ("controls.toml", 'id = "sc-13"', 'id = "si-10"', "duplicate control si-10"),
        ("controls.toml", 'id = "sc-13"', 'id = "SC13"', "control id 'SC13'"),
        ("controls.toml", '"tests/ai/test_audit.py::test_deleting_a_line_is_detected"', '"test_audit.py::x"', "test citation"),
        ("controls.toml", 'statement = "FIPS-validated cryptography."', 'statement = ""', "statement"),
        ("controls.toml", '[[control]]\nid = "si-10"', '[[control]\nid = "si-10"', "controls.toml"),
        ("system.toml", 'key = "harness"', 'key = "fuzzing"', "assessment keys"),
        ("stig.toml", 'component = "host"', 'component = "laptop"', "stig.toml: unknown component 'laptop'"),
        ("stig.toml", 'rules = ["UBTU-24-200020"]', 'rules = ["UBTU-24-100030"]', "more than one"),
        ("stig.toml", 'applied = ["UBTU-24-100030"', 'applied = ["UBTU-100030"', "STIG id 'UBTU-100030'"),
    ],
)
def test_sources_that_would_misstate_the_system_raise(tmp_path, filename, old, new, reason):
    directory = mutated(tmp_path, filename, old, new)
    with pytest.raises(SourceError, match=reason):
        load_sources(directory)


def test_implemented_without_automated_evidence_raises(tmp_path):
    directory = mutated(
        tmp_path,
        "controls.toml",
        'tests = [\n    "tests/test_cdm_codec.py::test_wrong_messages_are_rejected_with_a_named_reason",\n'
        '    "tests/test_cdm_codec.py::test_absent_covariance_degrades_to_geometry_only",\n]\n',
        "",
    )
    with pytest.raises(SourceError, match="si-10.*implemented.*automated evidence"):
        load_sources(directory)
