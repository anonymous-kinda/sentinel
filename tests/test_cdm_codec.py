"""CDM codec (ADR-001 seam): parsing, round trip, and the admission policy.

Wrong raises (CdmRejected); incomplete degrades (CdmWarning). Both paths
are exercised against real NASA files and against targeted mutations of
them, so a policy change shows up here as a named failure.
"""

import datetime as dt
import math
import pathlib

import numpy as np
import pytest

from sentinel.cdm import (
    CdmParseError,
    CdmRejected,
    emit,
    parse,
    parse_bytes,
    to_conjunction,
    validate,
)
from sentinel.cdm.timefmt import format_ccsds_time, parse_ccsds_time

CARA = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "cara"
ALL_CDMS = sorted(CARA.glob("*/*.cdm"))
FIXTURE_CDMS = sorted(CARA.parent.rglob("*.cdm"))
ALFANO_01 = CARA / "SampleCDMs" / "AlfanoTestCase01.cdm"
OPERATIONAL = CARA / "PcTestCaseCDMs" / "000025994_conj_000037558_20210324_151047_20210323_154356.cdm"


def _replace(text: str, key: str, new_line: str, occurrence: int = 1) -> str:
    """Replace the n-th line starting with `key` (followed by space or =)."""
    lines = text.splitlines()
    seen = 0
    for i, line in enumerate(lines):
        head = line.split("=")[0].strip()
        if head == key:
            seen += 1
            if seen == occurrence:
                lines[i] = new_line
                return "\n".join(lines) + "\n"
    raise AssertionError(f"{key} occurrence {occurrence} not found")


# --- time codes -----------------------------------------------------------
def test_parses_calendar_and_day_of_year_forms():
    a = parse_ccsds_time("2017-08-20T05:02:35.819")
    b = parse_ccsds_time("2017-232T05:02:35.819")
    assert a == b == dt.datetime(2017, 8, 20, 5, 2, 35, 819000, tzinfo=dt.UTC)


def test_time_parser_rejects_garbage_and_bad_day_of_year():
    with pytest.raises(ValueError):
        parse_ccsds_time("yesterday")
    with pytest.raises(ValueError):
        parse_ccsds_time("2021-400T00:00:00")


def test_time_formatting_is_utc_millisecond_form_a():
    when = dt.datetime(2026, 9, 23, 1, 2, 3, 456789, tzinfo=dt.UTC)
    assert format_ccsds_time(when) == "2026-09-23T01:02:03.456"
    with pytest.raises(ValueError):
        format_ccsds_time(when.replace(tzinfo=None))


# --- structure ------------------------------------------------------------
@pytest.mark.parametrize("path", ALL_CDMS, ids=[p.name for p in ALL_CDMS])
def test_every_nasa_cdm_parses_and_round_trips(path):
    message = parse_bytes(path.read_bytes())
    assert parse(emit(message)) == message
    assert message.objects[0].text("OBJECT") == "OBJECT1"
    assert message.objects[1].text("OBJECT") == "OBJECT2"


@pytest.mark.parametrize("path", FIXTURE_CDMS, ids=[p.name for p in FIXTURE_CDMS])
def test_every_real_cdm_under_fixtures_is_admitted(path):
    """The admission gates, the physical bounds among them, quarantine no real CDM."""
    to_conjunction(parse_bytes(path.read_bytes()))


def test_comments_and_units_survive_the_round_trip():
    message = parse_bytes(ALFANO_01.read_bytes())
    assert "HBR                        = 15.0" in message.preamble.comments()
    field = message.objects[0].get("CR_R")
    assert field.unit == "m**2"
    assert message.hbr_from_comment_m() == 15.0


def test_rejects_text_that_is_not_a_cdm():
    with pytest.raises(CdmParseError):
        parse("hello world")
    with pytest.raises(CdmParseError):
        parse("CCSDS_CDM_VERS = 1.0\nOBJECT = OBJECT1\n")
    with pytest.raises(CdmParseError):
        parse("CCSDS_CDM_VERS = 1.0\nOBJECT = OBJECT2\nOBJECT = OBJECT1\n")


# --- admission policy: incomplete degrades -----------------------------
def test_nasa_unit_label_anomaly_is_a_warning_not_a_rejection():
    """NASA's own Alfano CDMs label RELATIVE_VELOCITY_* as [m]."""
    warnings = validate(parse_bytes(ALFANO_01.read_bytes()))
    codes = {(w.code, w.key) for w in warnings}
    assert ("UNIT_LABEL_ANOMALY", "RELATIVE_VELOCITY_R") in codes


def test_absent_covariance_degrades_to_geometry_only():
    text = OPERATIONAL.read_text()
    for key in ("CR_R", "CT_R", "CT_T", "CN_R", "CN_T", "CN_N"):
        text = _replace(text, key, f"{key} = NaN [m**2]", occurrence=2)
    conversion = to_conjunction(parse(text))
    assert conversion.conjunction.secondary.covariance_rtn_m2 is None
    assert any(w.code == "COVARIANCE_ABSENT" and w.object_index == 1 for w in conversion.warnings)


# --- admission policy: wrong raises -----------------------------------------
@pytest.mark.parametrize(
    "key,line,occurrence,code",
    [
        ("X", "X = 7000.0 [m]", 1, "WRONG_UNIT"),
        ("X_DOT", "X_DOT = 7.5 [m/s]", 2, "WRONG_UNIT"),
        ("CR_R", "CR_R = 1.0 [km**2]", 1, "WRONG_UNIT"),
        ("REF_FRAME", "REF_FRAME = ITRF", 1, "UNSUPPORTED_REF_FRAME"),
        ("CT_T", "CT_T = NaN [m**2]", 1, "PARTIAL_COVARIANCE"),
        ("Y", "Y = NaN [km]", 2, "NONFINITE_STATE"),
        ("TCA", "TCA = tomorrow", 1, "BAD_TCA"),
        ("MISS_DISTANCE", "MISS_DISTANCE = 5000 [m]", 1, "MISS_DISTANCE_MISMATCH"),
    ],
)
def test_wrong_messages_are_rejected_with_a_named_reason(key, line, occurrence, code):
    text = _replace(OPERATIONAL.read_text(), key, line, occurrence)
    with pytest.raises(CdmRejected) as excinfo:
        to_conjunction(parse(text))
    assert excinfo.value.code == code


# --- conversion -------------------------------------------------------------
def test_conversion_carries_states_units_and_symmetric_covariance():
    message = parse_bytes(OPERATIONAL.read_bytes())
    conj = to_conjunction(message).conjunction
    assert conj.primary.object_id == message.object_designator(0)
    np.testing.assert_allclose(
        conj.primary.position_km, [message.objects[0].number(k) for k in ("X", "Y", "Z")]
    )
    cov = conj.primary.covariance_rtn_m2
    np.testing.assert_array_equal(cov, cov.T)
    assert cov[1, 0] == message.objects[0].number("CT_R")
    assert conj.tca == message.tca


def test_hbr_precedence_override_then_comment_then_area():
    message = parse_bytes(ALFANO_01.read_bytes())
    assert to_conjunction(message, hbr_override_m=8.0).hbr_source == "override"
    conv = to_conjunction(message)
    assert conv.hbr_source == "cdm_comment_hbr"
    assert conv.conjunction.primary.radius_m + conv.conjunction.secondary.radius_m == 15.0

    no_comment_text = "\n".join(
        line for line in ALFANO_01.read_text().splitlines() if not line.startswith("COMMENT HBR")
    )
    none = to_conjunction(parse(no_comment_text))
    assert none.hbr_source is None
    assert none.conjunction.primary.radius_m is None

    with_area = _replace(no_comment_text, "AREA_PC", "AREA_PC = 3.14159265358979 [m**2]", 1)
    with_area = _replace(with_area, "AREA_PC", "AREA_PC = 12.5663706143592 [m**2]", 2)
    area = to_conjunction(parse(with_area))
    assert area.hbr_source == "area_pc"
    assert math.isclose(area.conjunction.primary.radius_m, 1.0)
    assert math.isclose(area.conjunction.secondary.radius_m, 2.0)


def test_originator_asserted_pc_is_exposed_but_labelled_as_theirs():
    message = parse_bytes(OPERATIONAL.read_bytes())
    assert message.collision_probability == pytest.approx(0.02117)
    assert message.collision_probability_method == "FOSTER-1992"
