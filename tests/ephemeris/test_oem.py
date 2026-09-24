"""CCSDS Orbit Ephemeris Message (502.0-B-3), KVN subset: codec and admission."""

import dataclasses
import datetime as dt
import logging

import pytest

from sentinel.ephemeris import oem
from sentinel.ephemeris.table import EphemerisRejected

# A codec fixture: exercise-labelled, numbers chosen for the test, not a real
# ephemeris.
HEADER = """CCSDS_OEM_VERS = 3.0
COMMENT Codec test fixture - EXERCISE data, not a real ephemeris
CREATION_DATE = 2026-09-23T22:37:02.779
ORIGINATOR = SENTINEL-EXERCISE
"""

META = {
    "OBJECT_NAME": "EXSAT-1 (EXERCISE)",
    "OBJECT_ID": "99001",
    "CENTER_NAME": "EARTH",
    "REF_FRAME": "ITRF2014",
    "TIME_SYSTEM": "UTC",
    "START_TIME": "2026-09-24T06:00:00.000",
    "STOP_TIME": "2026-09-24T06:02:00.000",
    "INTERPOLATION": "LAGRANGE",
    "INTERPOLATION_DEGREE": "8",
}

DATA = [
    "2026-09-24T06:00:00.000 -2341.046 -4658.703 4661.458 1.234 -2.345 6.789",
    "2026-09-24T06:01:00.000 -2266.912 -4799.011 4251.337 1.236 -2.331 6.801",
    "2026-09-24T06:02:00.000 -2192.650 -4938.444 3840.402 1.239 -2.317 6.812",
]


def oem_text(meta=None, data=None, header=HEADER, drop=()):
    fields = {**META, **(meta or {})}
    meta_lines = "\n".join(f"{k} = {v}" for k, v in fields.items() if k not in drop)
    rows = "\n".join(DATA if data is None else data)
    return f"{header}\nMETA_START\n{meta_lines}\nMETA_STOP\n\n{rows}\n"


def rejected_code(text, **admit_args):
    with pytest.raises(EphemerisRejected) as caught:
        oem.admit(oem.parse(text), **admit_args)
    return caught.value.code


# --- codec -------------------------------------------------------------------

def test_parse_reads_header_metadata_and_states():
    message = oem.parse(oem_text())
    assert message.version == "3.0"
    assert message.creation_date == dt.datetime(2026, 9, 23, 22, 37, 2, 779000, tzinfo=dt.UTC)
    assert message.originator == "SENTINEL-EXERCISE"
    meta = message.metadata
    assert (meta.object_name, meta.object_id, meta.center_name) == ("EXSAT-1 (EXERCISE)", "99001", "EARTH")
    assert (meta.ref_frame, meta.time_system) == ("ITRF2014", "UTC")
    assert meta.start_time == dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
    assert meta.stop_time == dt.datetime(2026, 9, 24, 6, 2, tzinfo=dt.UTC)
    assert (meta.interpolation, meta.interpolation_degree) == ("LAGRANGE", 8)
    assert len(message.states) == 3
    first = message.states[0]
    assert first.epoch == dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
    assert first.position_km == (-2341.046, -4658.703, 4661.458)
    assert first.velocity_km_s == (1.234, -2.345, 6.789)
    assert first.acceleration_km_s2 is None


def test_interpolation_keywords_are_optional():
    message = oem.parse(oem_text(drop=("INTERPOLATION", "INTERPOLATION_DEGREE")))
    assert message.metadata.interpolation is None
    assert message.metadata.interpolation_degree is None


def test_emit_then_parse_is_the_identity():
    message = oem.parse(oem_text())
    assert oem.parse(oem.emit(message)) == message
    assert oem.emit(oem.parse(oem.emit(message))) == oem.emit(message)


def test_round_trip_keeps_microseconds_and_every_digit():
    # A millisecond is 7.6 m along-track in LEO: epochs must not be truncated.
    row = "2026-09-24T06:00:00.123456 -2341.0461234567891 -4658.703 4661.458 1.234 -2.345 6.789"
    message = oem.parse(oem_text(data=[row, *DATA[1:]]))
    again = oem.parse(oem.emit(message))
    assert again.states[0].epoch.microsecond == 123456
    assert again.states[0].position_km[0] == -2341.0461234567891
    assert again == message


def test_day_of_year_epochs_are_read():
    row = "2026-267T06:00:00.000 -2341.046 -4658.703 4661.458 1.234 -2.345 6.789"
    message = oem.parse(oem_text(data=[row, *DATA[1:]]))
    assert message.states[0].epoch == dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)


def test_states_may_carry_accelerations_and_they_survive_a_round_trip():
    row = DATA[0] + " 0.001 -0.002 0.003"
    message = oem.parse(oem_text(data=[row, *DATA[1:]]))
    assert message.states[0].acceleration_km_s2 == (0.001, -0.002, 0.003)
    assert oem.parse(oem.emit(message)) == message


def test_a_state_without_velocity_is_read_as_position_only():
    rows = [" ".join(line.split()[:4]) for line in DATA]
    message = oem.parse(oem_text(data=rows))
    assert all(state.velocity_km_s is None for state in message.states)
    assert oem.parse(oem.emit(message)) == message


def parse_code(text):
    with pytest.raises(EphemerisRejected) as caught:
        oem.parse(text)
    return caught.value.code


@pytest.mark.parametrize("bad", ["-2341.0x6", "nan", "inf", "1,5"])
def test_a_malformed_number_is_rejected(bad):
    row = f"2026-09-24T06:00:00.000 {bad} -4658.703 4661.458 1.234 -2.345 6.789"
    assert parse_code(oem_text(data=[row, *DATA[1:]])) == "MALFORMED_NUMBER"


def test_a_malformed_interpolation_degree_is_rejected():
    assert parse_code(oem_text(meta={"INTERPOLATION_DEGREE": "eight"})) == "MALFORMED_NUMBER"


def test_a_malformed_time_is_rejected():
    for epoch in ("2026/09/24T06:00:00", "2026-09-24T25:00:00"):
        row = f"{epoch} -2341.046 -4658.703 4661.458 1.234 -2.345 6.789"
        assert parse_code(oem_text(data=[row, *DATA[1:]])) == "MALFORMED_TIME"
    assert parse_code(oem_text(meta={"START_TIME": "yesterday"})) == "MALFORMED_TIME"


def test_a_data_line_with_the_wrong_number_of_values_is_rejected():
    row = "2026-09-24T06:00:00.000 -2341.046 -4658.703 4661.458 1.234"
    assert parse_code(oem_text(data=[row, *DATA[1:]])) == "MALFORMED_LINE"


def test_a_keyword_line_without_a_value_is_rejected():
    assert parse_code(HEADER + "ORIGINATOR\n") == "MALFORMED_LINE"


def test_a_repeated_keyword_is_rejected_rather_than_one_value_chosen():
    text = oem_text().replace("REF_FRAME = ITRF2014", "REF_FRAME = ITRF2014\nREF_FRAME = EME2000")
    assert parse_code(text) == "DUPLICATE_KEYWORD"


def test_text_without_an_oem_version_is_not_an_oem():
    assert parse_code(oem_text(header="CREATION_DATE = 2026-09-23T22:37:02\nORIGINATOR = X\n")) == "NOT_AN_OEM"
    assert parse_code("CCSDS_CDM_VERS = 1.0\nCREATION_DATE = 2026-09-23T22:37:02\n") == "NOT_AN_OEM"
    assert parse_code("") == "NOT_AN_OEM"


@pytest.mark.parametrize("bad", ["1_000.0", "0x1p3", "1.5.2", "+-2"])
def test_numbers_are_read_to_the_ccsds_grammar_not_python_float(bad):
    row = f"2026-09-24T06:00:00.000 {bad} -4658.703 4661.458 1.234 -2.345 6.789"
    assert parse_code(oem_text(data=[row, *DATA[1:]])) == "MALFORMED_NUMBER"


@pytest.mark.parametrize("key", ["OBJECT_NAME", "OBJECT_ID", "CENTER_NAME", "REF_FRAME", "TIME_SYSTEM", "START_TIME", "STOP_TIME"])
def test_a_missing_required_metadata_keyword_is_rejected(key):
    assert parse_code(oem_text(drop=(key,))) == "MISSING_KEYWORD"


def test_missing_creation_date_is_rejected():
    header = "CCSDS_OEM_VERS = 3.0\nORIGINATOR = SENTINEL-EXERCISE\n"
    assert parse_code(oem_text(header=header)) == "MISSING_KEYWORD"


def test_keywords_outside_the_subset_are_refused_rather_than_ignored():
    # USEABLE_START_TIME narrows where the data may be used; ignoring it
    # could interpolate where the originator says not to.
    assert parse_code(oem_text(meta={"USEABLE_START_TIME": "2026-09-24T06:00:30"})) == "UNSUPPORTED_KEYWORD"


def test_a_second_segment_is_refused():
    text = oem_text()
    second = text[text.index("META_START"):]
    assert parse_code(text + "\n" + second) == "UNSUPPORTED_SEGMENTS"


def test_a_covariance_block_is_refused():
    text = oem_text() + "COVARIANCE_START\nEPOCH = 2026-09-24T06:00:00\nCOVARIANCE_STOP\n"
    assert parse_code(text) == "UNSUPPORTED_BLOCK"


def test_parse_bytes_accepts_utf8_with_a_bom():
    message = oem.parse_bytes(("﻿" + oem_text()).encode("utf-8"))
    assert message.originator == "SENTINEL-EXERCISE"


# --- admission: OEM to StateTable ----------------------------------------------

def test_an_itrf_utc_message_is_admitted_as_a_state_table():
    admission = oem.admit(oem.parse(oem_text()))
    table = admission.table
    assert admission.warnings == ()
    assert table.norad_id == 99001
    assert table.name == "EXSAT-1 (EXERCISE)"
    assert table.created == dt.datetime(2026, 9, 23, 22, 37, 2, 779000, tzinfo=dt.UTC)
    assert table.epochs[1] == dt.datetime(2026, 9, 24, 6, 1, tzinfo=dt.UTC)
    assert table.positions_km[2].tolist() == [-2192.650, -4938.444, 3840.402]


def test_an_international_designator_needs_the_catalog_number_from_the_caller():
    text = oem_text(meta={"OBJECT_ID": "2014-048A"})
    assert rejected_code(text) == "NORAD_ID_UNKNOWN"
    assert oem.admit(oem.parse(text), norad_id=40115).table.norad_id == 40115


def test_an_object_id_that_only_looks_numeric_is_not_taken_as_a_catalog_number():
    assert rejected_code(oem_text(meta={"OBJECT_ID": "4011²"})) == "NORAD_ID_UNKNOWN"


def test_a_catalog_number_that_contradicts_the_message_is_rejected():
    assert rejected_code(oem_text(), norad_id=40115) == "NORAD_ID_MISMATCH"
    assert oem.admit(oem.parse(oem_text()), norad_id=99001).table.norad_id == 99001


@pytest.mark.parametrize("frame", ["EME2000", "GCRF", "TEME"])
def test_an_inertial_frame_is_rejected(frame):
    assert rejected_code(oem_text(meta={"REF_FRAME": frame})) == "REF_FRAME_NOT_EARTH_FIXED"


@pytest.mark.parametrize("system", ["TAI", "GPS", "TT"])
def test_a_time_system_other_than_utc_is_rejected(system):
    assert rejected_code(oem_text(meta={"TIME_SYSTEM": system})) == "TIME_SYSTEM_NOT_UTC"


def test_a_centre_other_than_the_earth_is_rejected():
    assert rejected_code(oem_text(meta={"CENTER_NAME": "MOON"})) == "CENTER_NOT_EARTH"


def test_epochs_out_of_order_are_rejected():
    assert rejected_code(oem_text(data=[DATA[0], DATA[2], DATA[1]])) == "EPOCHS_NOT_INCREASING"


def test_a_message_with_no_states_is_rejected():
    assert rejected_code(oem_text(data=[])) == "TOO_FEW_STATES"


def test_missing_velocities_degrade_with_a_recorded_and_logged_warning(caplog):
    rows = [" ".join(line.split()[:4]) for line in DATA]
    with caplog.at_level(logging.WARNING, logger="sentinel.ephemeris.oem"):
        admission = oem.admit(oem.parse(oem_text(data=rows)))
    assert [w.code for w in admission.warnings] == ["VELOCITY_ABSENT"]
    assert admission.table.positions_km.shape == (3, 3)
    record = next(r for r in caplog.records if r.getMessage() == "Ephemeris admitted incomplete")
    assert record.fields["code"] == "VELOCITY_ABSENT"
    assert record.fields["object_id"] == "99001"


def test_the_message_model_is_immutable():
    message = oem.parse(oem_text())
    with pytest.raises(dataclasses.FrozenInstanceError):
        message.originator = "SOMEONE-ELSE"
