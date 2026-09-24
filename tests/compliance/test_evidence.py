"""Matching what the SSP cites against what a CI run actually did.

A citation that matched nothing is not a pass: the test was renamed, deleted
or not run, and the SSP is citing evidence that no longer exists.
"""

import dataclasses
import pathlib

import pytest

from compliance.evidence import assess, cites, unmapped_failures
from compliance.inputs import CaseResult, read_harness, read_junit
from compliance.sources import load_sources

DATA = pathlib.Path(__file__).parent / "data"


def with_evidence(control, **changes):
    """The control with its first contribution's evidence replaced."""
    first = dataclasses.replace(control.contributions[0], **changes)
    return dataclasses.replace(control, contributions=(first,))


@pytest.fixture(scope="module")
def controls():
    return {c.id: c for c in load_sources(DATA / "sources").controls}


@pytest.fixture(scope="module")
def run():
    return read_junit(DATA / "junit_mixed.xml")


@pytest.mark.parametrize(
    ("citation", "classname", "name", "expected"),
    [
        ("tests/test_cdm_codec.py::test_absent", "tests.test_cdm_codec", "test_absent", True),
        ("tests/test_cdm_codec.py::test_absent", "tests.test_cdm_codec", "test_absent[case]", True),
        ("tests/test_cdm_codec.py::test_absent", "tests.test_cdm_codec", "test_absent_more", False),
        ("tests/test_cdm_codec.py::test_absent", "tests.test_cdm_codecs", "test_absent", False),
        ("tests/property/test_crdt.py::TestDDILNetwork::runTest", "tests.property.test_crdt.TestDDILNetwork", "runTest", True),
        ("tests/property/test_crdt.py::TestDDILNetwork", "tests.property.test_crdt.TestDDILNetwork", "runTest", True),
        ("tests/test_cdm_codec.py", "tests.test_cdm_codec", "test_anything", True),
        ("tests/test_cdm_codec.py", "tests.test_cdm_codec_extra", "test_anything", False),
    ],
)
def test_a_citation_matches_its_cases(citation, classname, name, expected):
    assert cites(citation, CaseResult(classname, name, "passed")) is expected


def test_passing_citations_satisfy_the_control(controls, run):
    (si10,) = assess([controls["si-10"]], run, harness=None)
    assert [c.state for c in si10.citations] == ["passed", "passed"]
    assert si10.citations[0].detail == "2 cases passed"
    assert si10.satisfied and not si10.failed and not si10.missing


def test_a_failure_or_error_fails_the_citation_and_keeps_the_message(controls, run):
    (au9,) = assess([controls["au-9"]], run, harness=None)
    editing, deleting = au9.citations[:2]
    assert editing.state == "failed" and "AssertionError: assert True is False" in editing.detail
    assert deleting.state == "failed" and "fixture 'tmp_path' not found" in deleting.detail
    assert not au9.satisfied and len(au9.failed) == 2


def test_harness_evidence_is_not_supplied_unless_given(controls, run):
    (au9,) = assess([controls["au-9"]], run, harness=None)
    assert au9.citations[2].kind == "harness" and au9.citations[2].state == "not-supplied"
    (au9,) = assess([controls["au-9"]], run, harness=read_harness(DATA / "harness"))
    assert au9.citations[2].state == "passed"


def test_a_failed_harness_scenario_fails_its_citation(controls, run):
    control = with_evidence(controls["au-9"], harness=("recovery",))
    (result,) = assess([control], run, harness=read_harness(DATA / "harness"))
    assert result.citations[2].state == "failed"
    assert "operator data written while denied" in result.citations[2].detail


def test_a_citation_that_matched_nothing_is_missing_not_passed(controls, run):
    control = with_evidence(controls["si-10"], tests=("tests/test_cdm_codec.py::test_that_was_renamed",))
    (result,) = assess([control], run, harness=None)
    assert result.citations[0].state == "missing" and result.citations[0].detail == "not in this run"
    assert result.missing and not result.satisfied


def test_skipped_cases_are_not_evidence(controls, run):
    control = with_evidence(controls["si-10"], tests=("tests/test_tier5_refusal.py::test_zero_covariance_is_refused",))
    (result,) = assess([control], run, harness=None)
    assert result.citations[0].state == "missing" and result.citations[0].detail == "1 case skipped"


def test_a_control_with_no_automated_citations_is_not_observed(controls, run):
    (sc13,) = assess([controls["sc-13"]], run, harness=None)
    assert sc13.citations == () and not sc13.observed and not sc13.satisfied


def test_failures_no_control_cites_are_still_reported(controls, run):
    only_si10 = [controls["si-10"]]
    assert [c.name for c in unmapped_failures(only_si10, run)] == [
        "test_editing_a_line_is_detected_at_that_line",
        "test_deleting_a_line_is_detected",
    ]
    assert unmapped_failures(list(controls.values()), run) == ()
