"""DISA STIG and CCI data, read from the vendored upstream files.

Expected values below were read from DISA's published V1R6 XCCDF and the
2025-01-23 CCI list by eye, not produced by this code.
"""

import pathlib

import pytest

from compliance.stig import control_ids, load_benchmark, load_cci_rev5

ROOT = pathlib.Path(__file__).resolve().parents[2]
XCCDF = ROOT / "compliance/vendor/disa/U_CAN_Ubuntu_24-04_LTS_STIG_V1R6_Manual-xccdf.xml"
CCI = ROOT / "compliance/vendor/disa/U_CCI_List.zip"


@pytest.fixture(scope="module")
def benchmark():
    return load_benchmark(XCCDF)


def test_benchmark_release_and_rule_count(benchmark):
    assert benchmark.release == "V1R6"
    assert benchmark.date == "01 Jul 2026"
    assert len(benchmark.rules) == 194


def test_a_rule_carries_its_ids_severity_and_ccis(benchmark):
    rule = benchmark.rules["UBTU-24-100030"]
    assert rule.vuln_id == "V-270647"
    assert rule.rule_id == "SV-270647r1066430_rule"
    assert rule.severity == "high"
    assert rule.title == "Ubuntu 24.04 LTS must not have the telnet package installed."
    assert rule.ccis == ("CCI-000197",)
    assert rule.vuln_key == "SV-270647"


def test_cci_list_maps_to_rev5_references():
    rev5 = load_cci_rev5(CCI)
    assert rev5["CCI-002450"] == ("SC-13 b",)
    assert rev5["CCI-000197"] == ("IA-5 (1) (c)",)


@pytest.mark.parametrize(
    ("refs", "expected"),
    [
        (("SC-13 b",), ("sc-13",)),
        (("IA-5 (1) (c)",), ("ia-5.1",)),
        (("AC-17 (2)", "MA-4 (6)", "SC-8 (1)"), ("ac-17.2", "ma-4.6", "sc-8.1")),
        (("AU-12 c", "AC-2 (4)", "AU-12 c"), ("ac-2.4", "au-12")),
    ],
)
def test_rev5_references_become_oscal_control_ids(refs, expected):
    assert control_ids(refs) == expected


def test_a_reference_that_is_not_a_control_raises():
    with pytest.raises(ValueError, match="not an 800-53 reference"):
        control_ids(("section 3.1",))
