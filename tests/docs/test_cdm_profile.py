"""docs/icd/cdm-profile.md against the CDM codec and the admission path.

Every rejection and warning code the code can produce is in the profile's
tables, and every code the tables list is one the code can still produce.
Units, frames, the physical bounds and the data-class marks are held to
the constants that enforce them. The codes are read from the source
(sentinel/cdm and the service's quarantine calls), not restated here.
"""

from sentinel.cdm.model import POSITION_COVARIANCE_KEYS, STATE_POSITION_KEYS, STATE_VELOCITY_KEYS
from sentinel.cdm.validate import (
    _COVARIANCE_UNIT,
    _POSITION_UNIT,
    _SUMMARY_UNITS,
    _VELOCITY_UNIT,
    EARLIEST_TCA,
    INERTIAL_FRAMES,
    MAX_POSITION_VARIANCE_M2,
    MAX_RADIUS_KM,
    MAX_SPEED_KM_S,
    WGS84_POLAR_RADIUS_KM,
)
from sentinel.conjunction.service import EVENT_TCA_WINDOW_S, ORIGINATOR_DATA_CLASS
from sentinel.screening.derived_cdm import DEMONSTRATION_COMMENT

from .icd import ICD, backticked, call_arguments, column, compare, drop_row, table_rows, trees

PROFILE = ICD / "cdm-profile.md"
CODEC = trees("sentinel/cdm/*.py")
SERVICE = trees("sentinel/conjunction/service.py")
QUARANTINE, DEGRADE = "WRONG_UNIT", "UNIT_LABEL_ANOMALY"


def rejection_codes() -> set[str]:
    return call_arguments(CODEC, "CdmRejected", 0) | call_arguments(SERVICE, "_reject", 2)


def warning_codes() -> set[str]:
    return call_arguments(CODEC, "CdmWarning", 0)


def unit_rules() -> set[tuple[str, str, str]]:
    """(keyword, required unit label, code when it is labelled otherwise)."""
    load_bearing = (
        (STATE_POSITION_KEYS, _POSITION_UNIT),
        (STATE_VELOCITY_KEYS, _VELOCITY_UNIT),
        (POSITION_COVARIANCE_KEYS, _COVARIANCE_UNIT),
    )
    rules = {(key, unit, QUARANTINE) for keys, unit in load_bearing for key in keys}
    return rules | {(key, unit, DEGRADE) for key, unit in _SUMMARY_UNITS.items()}


def documented_unit_rules(doc: str) -> set[tuple[str, str, str]]:
    rules = set()
    for keywords, unit, code, *_ in table_rows(doc, "Units"):
        rules |= {(key, backticked(unit)[0], backticked(code)[0]) for key in backticked(keywords)}
    return rules


def physical_bounds() -> set[str]:
    """What the "Admitted" column must say, formatted from the constants."""
    return {
        f"{WGS84_POLAR_RADIUS_KM:,.3f} km to {MAX_RADIUS_KM:,.0f} km",
        f"at most {MAX_SPEED_KM_S:,.0f} km/s",
        f"magnitude at most `{MAX_POSITION_VARIANCE_M2:.3g}` m**2",
    }


def documented_bounds(doc: str) -> set[str]:
    return {admitted for _quantity, admitted, *_ in table_rows(doc, "Physical bounds")}


def documented_marks(doc: str) -> set[tuple[str, str]]:
    return {
        (backticked(originator)[0], backticked(data_class)[0])
        for originator, data_class, *_ in table_rows(doc, "Data class")
        if backticked(originator)
    }


def profile_problems(doc: str) -> list[str]:
    problems = compare(column(doc, "Rejection codes"), rejection_codes(), "rejection code")
    problems += compare(column(doc, "Warning codes"), warning_codes(), "warning code")
    problems += compare(column(doc, "Frames"), set(INERTIAL_FRAMES), "frame")
    problems += compare(documented_unit_rules(doc), unit_rules(), "unit rule")
    problems += compare(documented_bounds(doc), physical_bounds(), "physical bound")
    problems += compare(documented_marks(doc), set(ORIGINATOR_DATA_CLASS.items()), "data-class mark")
    if DEMONSTRATION_COMMENT not in doc:
        problems.append("the DERIVED demonstration COMMENT is not quoted")
    if f"{EARLIEST_TCA:%Y-%m-%d}" not in doc:
        problems.append(f"the earliest TCA, {EARLIEST_TCA:%Y-%m-%d}, is not stated")
    if f"{EVENT_TCA_WINDOW_S:g} s" not in doc:
        problems.append(f"the {EVENT_TCA_WINDOW_S:g} s event window is not stated")
    return problems


def test_the_source_yields_the_codes_it_is_known_to_raise():
    assert {"PARSE_ERROR", "UNREADABLE", "WRONG_UNIT", "PARTIAL_COVARIANCE"} <= rejection_codes()
    assert {"COVARIANCE_ABSENT", "UNIT_LABEL_ANOMALY"} <= warning_codes()


def test_the_profile_matches_the_code():
    assert profile_problems(PROFILE.read_text()) == []


def test_a_stale_profile_is_caught():
    doc = PROFILE.read_text()
    assert profile_problems(drop_row(doc, "PARTIAL_COVARIANCE")) == [
        "rejection code PARTIAL_COVARIANCE is not documented"
    ]
    assert profile_problems(drop_row(doc, "COVARIANCE_ABSENT")) == ["warning code COVARIANCE_ABSENT is not documented"]
    assert profile_problems(drop_row(doc, "GCRF")) == ["frame GCRF is not documented"]
    retired = doc.replace("| `PARSE_ERROR` |", "| `RETIRED_CODE` | - | - |\n| `PARSE_ERROR` |", 1)
    assert profile_problems(retired) == ["rejection code RETIRED_CODE is documented but not in the code"]
    relabelled = doc.replace("| `km/s` |", "| `m/s` |", 1)
    assert "unit rule ('X_DOT', 'km/s', 'WRONG_UNIT') is not documented" in profile_problems(relabelled)
    later = doc.replace(f"{EARLIEST_TCA:%Y-%m-%d}", "1958-01-31")
    assert profile_problems(later) == [f"the earliest TCA, {EARLIEST_TCA:%Y-%m-%d}, is not stated"]
    faster = doc.replace("| at most 100 km/s |", "| at most 200 km/s |", 1)
    assert profile_problems(faster) == [
        "physical bound at most 100 km/s is not documented",
        "physical bound at most 200 km/s is documented but not in the code",
    ]
