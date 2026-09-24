"""Evidence readers: JUnit XML, DDIL harness results, OpenSCAP XCCDF results.

The ARMOR rule applies to evidence as much as to CDMs: input that would make
the assessment wrong raises, input that makes it incomplete degrades and says
so.
"""

import datetime as dt
import pathlib

import pytest

from compliance.inputs import EvidenceError, read_harness, read_junit, read_xccdf

DATA = pathlib.Path(__file__).parent / "data"


# ---------------------------------------------------------------------- JUnit
def test_junit_run_carries_an_aware_start_time_and_duration():
    run = read_junit(DATA / "junit_mixed.xml")
    assert run.started == dt.datetime(2026, 9, 23, 20, 4, 17, 525661, tzinfo=dt.timezone(dt.timedelta(hours=-10)))
    assert run.duration_s == pytest.approx(2.5)


def test_junit_outcomes_are_read_per_case():
    outcomes = {(c.classname, c.name): c.outcome for c in read_junit(DATA / "junit_mixed.xml").cases}
    assert outcomes[("tests.test_cdm_codec", "test_absent_covariance_degrades_to_geometry_only")] == "passed"
    assert outcomes[("tests.property.test_crdt.TestDDILNetwork", "runTest")] == "passed"
    assert outcomes[("tests.ai.test_audit", "test_editing_a_line_is_detected_at_that_line")] == "failed"
    assert outcomes[("tests.ai.test_audit", "test_deleting_a_line_is_detected")] == "error"
    assert outcomes[("tests.test_tier5_refusal", "test_zero_covariance_is_refused")] == "skipped"


def test_junit_failure_keeps_its_message():
    case = next(c for c in read_junit(DATA / "junit_mixed.xml").cases if c.outcome == "failed")
    assert case.message == "AssertionError: assert True is False"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("<testsuites><testsuite", "not well-formed"),
        ("<testsuites></testsuites>", "no testsuite"),
        ('<testsuite name="pytest" time="1"><testcase classname="a" name="b"/></testsuite>', "no timestamp"),
        ('<testsuite timestamp="2026-09-23T20:04:17" time="1"><testcase classname="a" name="b"/></testsuite>', "UTC offset"),
        ('<testsuite timestamp="2026-09-23T20:04:17Z" time="1"></testsuite>', "no testcases"),
    ],
)
def test_junit_that_would_mislead_the_assessment_raises(tmp_path, text, reason):
    path = tmp_path / "junit.xml"
    path.write_text(text)
    with pytest.raises(EvidenceError, match=reason):
        read_junit(path)


def test_missing_junit_file_raises(tmp_path):
    with pytest.raises(EvidenceError, match="not found"):
        read_junit(tmp_path / "absent.xml")


# -------------------------------------------------------------------- harness
def test_harness_results_are_keyed_by_scenario():
    results = read_harness(DATA / "harness")
    assert set(results) == {"denied", "recovery"}
    assert results["denied"].passed and results["denied"].failed_assertions == ()
    assert not results["recovery"].passed
    assert results["recovery"].failed_assertions == (
        "operator data written while denied reaches the hub over the thin link (converged in 180.0 s)",
    )
    assert results["denied"].ran_at == "2026-09-24T02:39:10.000000+00:00"


def test_an_empty_harness_directory_is_incomplete_not_wrong(tmp_path):
    assert read_harness(tmp_path) == {}


def test_a_harness_file_without_assertions_raises(tmp_path):
    (tmp_path / "denied.json").write_text('{"scenario": "DENIED", "passed": true}')
    with pytest.raises(EvidenceError, match="assertions"):
        read_harness(tmp_path)


def test_a_harness_file_that_is_not_json_raises(tmp_path):
    (tmp_path / "denied.json").write_text("{")
    with pytest.raises(EvidenceError, match="denied.json"):
        read_harness(tmp_path)


def test_a_missing_harness_directory_raises(tmp_path):
    with pytest.raises(EvidenceError, match="not found"):
        read_harness(tmp_path / "absent")


# ---------------------------------------------------------------------- XCCDF
def test_xccdf_results_map_rule_ids_to_stig_ids_from_the_benchmark():
    scan = read_xccdf(DATA / "xccdf_results.xml")
    by_vuln = {r.vuln_key: r for r in scan.results}
    assert by_vuln["SV-270647"].stig_id == "UBTU-24-100030" and by_vuln["SV-270647"].result == "pass"
    assert by_vuln["SV-270667"].result == "fail"
    assert by_vuln["SV-270678"].result == "notapplicable"
    # Not described by a Rule element in this results file: still reported.
    assert by_vuln["SV-270746"].stig_id is None and by_vuln["SV-270746"].result == "error"


def test_xccdf_scan_records_target_profile_and_times():
    scan = read_xccdf(DATA / "xccdf_results.xml")
    assert scan.target == "sentinel-hub"
    assert scan.profile == "xccdf_mil.disa.stig_profile_MAC-2_Sensitive"
    assert scan.started == dt.datetime(2026, 9, 23, 10, 0, tzinfo=dt.UTC)
    assert scan.finished == dt.datetime(2026, 9, 23, 10, 2, 30, tzinfo=dt.UTC)


def test_xccdf_without_a_test_result_raises(tmp_path):
    path = tmp_path / "x.xml"
    path.write_text('<Benchmark xmlns="http://checklists.nist.gov/xccdf/1.2" id="b"/>')
    with pytest.raises(EvidenceError, match="TestResult"):
        read_xccdf(path)


def test_an_unknown_rule_result_raises_rather_than_hiding_a_failure(tmp_path):
    text = (DATA / "xccdf_results.xml").read_text().replace("<result>pass</result>", "<result>maybe</result>")
    path = tmp_path / "x.xml"
    path.write_text(text)
    with pytest.raises(EvidenceError, match="maybe"):
        read_xccdf(path)
