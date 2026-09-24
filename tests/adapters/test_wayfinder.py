"""Wayfinder adapter: contract tests against an ASSUMED schema.

The schema is Sentinel's assumption, not Wayfinder's published contract
(docs/adapters/wayfinder.md). When real API access is granted, replace the
fixture with a real response and parse_ephemeris with the real mapping;
these tests are the checklist for that swap.
"""

import copy
import datetime as dt
import hashlib
import json
import logging

import numpy as np
import pytest

from sentinel.adapters import wayfinder
from sentinel.ephemeris.table import EphemerisRejected
from sentinel.ephemeris.tabulate import tabulate
from sentinel.passes.model import Imager, Unit
from sentinel.passes.providers.tabulated import TabulatedEphemerisProvider
from tests.omm_snapshot import ROOT, TIMESCALE, omm_records, satellite

FIXTURE_DIR = ROOT / "fixtures" / "wayfinder"
FIXTURE = FIXTURE_DIR / "ASSUMED-ephemeris-worldview3.json"
FIXTURE_START = dt.datetime(2026, 9, 24, 5, 0, tzinfo=dt.UTC)
FIXTURE_STOP = dt.datetime(2026, 9, 25, 7, 0, tzinfo=dt.UTC)

SMALL = {
    "object": {"norad_id": 99001, "name": "EXSAT-1 (EXERCISE)"},
    "frame": "ITRF",
    "time_system": "UTC",
    "created": "2026-09-23T22:37:02.779392Z",
    "epochs": ["2026-09-24T06:00:00Z", "2026-09-24T06:01:00Z", "2026-09-24T06:02:00Z"],
    "positions_km": [[-2341.046, -4658.703, 4661.458], [-2266.912, -4799.011, 4251.337], [-2192.65, -4938.444, 3840.402]],
}


def payload(**changes):
    body = copy.deepcopy(SMALL)
    body.update(changes)
    return body


def rejected_code(body):
    with pytest.raises(EphemerisRejected) as caught:
        wayfinder.parse_ephemeris(body)
    return caught.value.code


# --- the parser --------------------------------------------------------------

def test_the_schema_is_declared_as_assumed():
    assert wayfinder.SCHEMA_STATUS == "ASSUMED"


def test_a_payload_in_the_assumed_schema_becomes_a_state_table():
    table = wayfinder.parse_ephemeris(payload())
    assert (table.norad_id, table.name) == (99001, "EXSAT-1 (EXERCISE)")
    assert table.created == dt.datetime(2026, 9, 23, 22, 37, 2, 779392, tzinfo=dt.UTC)
    assert table.epochs[2] == dt.datetime(2026, 9, 24, 6, 2, tzinfo=dt.UTC)
    assert table.positions_km[1].tolist() == [-2266.912, -4799.011, 4251.337]


def test_every_parse_is_logged_as_coming_from_an_assumed_schema(caplog):
    with caplog.at_level(logging.INFO, logger="sentinel.adapters.wayfinder"):
        wayfinder.parse_ephemeris(payload())
    (record,) = [r for r in caplog.records if r.getMessage() == "Ephemeris parsed from assumed schema"]
    assert record.fields == {"adapter": "wayfinder", "norad_id": 99001, "states": 3}


def test_unknown_keys_are_ignored():
    assert wayfinder.parse_ephemeris(payload(extra={"anything": 1})).norad_id == 99001


def test_offsets_are_converted_to_utc():
    epochs = ["2026-09-24T08:00:00+02:00", "2026-09-24T06:01:00Z", "2026-09-24T06:02:00.000000+00:00"]
    table = wayfinder.parse_ephemeris(payload(epochs=epochs))
    assert table.epochs[0] == dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
    assert table.epochs[0].tzinfo == dt.UTC


@pytest.mark.parametrize("key", ["object", "frame", "time_system", "created", "epochs", "positions_km"])
def test_a_missing_field_is_a_schema_mismatch(key):
    body = payload()
    del body[key]
    assert rejected_code(body) == "SCHEMA_MISMATCH"


@pytest.mark.parametrize("key", ["norad_id", "name"])
def test_a_missing_object_field_is_a_schema_mismatch(key):
    body = payload()
    del body["object"][key]
    assert rejected_code(body) == "SCHEMA_MISMATCH"


@pytest.mark.parametrize(
    "changes",
    [
        {"object": {"norad_id": "40115", "name": "X"}},
        {"object": {"norad_id": True, "name": "X"}},
        {"object": {"norad_id": 40115, "name": 7}},
        {"frame": ["ITRF"]},
        {"epochs": "2026-09-24T06:00:00Z"},
        {"positions_km": [[1.0, 2.0, "3.0"], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]},
        {"positions_km": [[1.0, 2.0], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]},
        {"positions_km": [[1.0, 2.0, True], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]},
        {"positions_km": {"x": [1.0]}},
    ],
)
def test_a_mistyped_field_is_a_schema_mismatch(changes):
    assert rejected_code(payload(**changes)) == "SCHEMA_MISMATCH"


def test_an_inertial_frame_is_rejected():
    assert rejected_code(payload(frame="EME2000")) == "REF_FRAME_NOT_EARTH_FIXED"


def test_a_time_system_other_than_utc_is_rejected():
    assert rejected_code(payload(time_system="TAI")) == "TIME_SYSTEM_NOT_UTC"


def test_a_malformed_time_is_rejected():
    assert rejected_code(payload(created="yesterday")) == "MALFORMED_TIME"


def test_a_time_without_a_zone_is_rejected():
    assert rejected_code(payload(created="2026-09-23T22:37:02")) == "NAIVE_TIME"


def test_epochs_out_of_order_are_rejected():
    epochs = [SMALL["epochs"][0], SMALL["epochs"][2], SMALL["epochs"][1]]
    assert rejected_code(payload(epochs=epochs)) == "EPOCHS_NOT_INCREASING"


def test_as_many_positions_as_epochs_are_required():
    assert rejected_code(payload(positions_km=SMALL["positions_km"][:2])) == "SHAPE_MISMATCH"


def test_load_reads_json_bytes_and_refuses_anything_else():
    assert wayfinder.load_ephemeris(json.dumps(payload()).encode()).norad_id == 99001
    for bad in (b"not json", b"[1, 2, 3]"):
        with pytest.raises(EphemerisRejected) as caught:
            wayfinder.load_ephemeris(bad)
        assert caught.value.code == "SCHEMA_MISMATCH"


# --- the contract fixture ----------------------------------------------------

@pytest.fixture(scope="module")
def fixture_bytes():
    return FIXTURE.read_bytes()


@pytest.fixture(scope="module")
def fixture_table(fixture_bytes):
    return wayfinder.load_ephemeris(fixture_bytes)


def test_the_fixture_says_it_is_an_assumed_schema_and_derived_data(fixture_bytes):
    label = json.loads(fixture_bytes)["_sentinel"]
    assert FIXTURE.name.startswith("ASSUMED-")
    assert label["schema"] == "ASSUMED"
    assert label["data_class"] == "DERIVED"
    assert "not Wayfinder output" in label["note"]


def test_the_fixture_matches_its_recorded_checksum(fixture_bytes):
    sums = dict(reversed(line.split()) for line in (FIXTURE_DIR / "SHA256SUMS").read_text().splitlines())
    assert sums[FIXTURE.name] == hashlib.sha256(fixture_bytes).hexdigest()


def test_the_fixture_parses_into_a_worldview3_table_for_the_exercise_day(fixture_table):
    assert (fixture_table.norad_id, fixture_table.name) == (40115, "WORLDVIEW-3 (WV-3)")
    assert (fixture_table.start, fixture_table.stop) == (FIXTURE_START, FIXTURE_STOP)
    assert len(fixture_table.epochs) == 26 * 60 + 1
    epoch = omm_records()[40115]["EPOCH"]
    assert fixture_table.created == dt.datetime.fromisoformat(epoch).replace(tzinfo=dt.UTC)


def test_the_fixture_is_worldview3_propagated_from_the_public_element_set(fixture_table):
    # Provenance, checked rather than asserted: every number in the fixture is
    # SGP4 of the public CelesTrak element set, to the 1 mm it was rounded to.
    direct = tabulate(satellite(40115), TIMESCALE, FIXTURE_START, FIXTURE_STOP, step_s=60.0)
    assert fixture_table.epochs == direct.epochs
    assert np.abs(fixture_table.positions_km - direct.positions_km).max() < 1e-5


def test_the_adapter_feeds_the_tabulated_provider_like_any_other_table(fixture_table):
    unit = Unit("NTC-EXERCISE", 35.26, -116.68)
    wv3 = Imager(40115, "WORLDVIEW-3", "EO", 45.0, basis="test assumption")
    start, end = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC), dt.datetime(2026, 9, 25, 6, 0, tzinfo=dt.UTC)
    direct = tabulate(satellite(40115), TIMESCALE, FIXTURE_START, FIXTURE_STOP, step_s=60.0)
    via_adapter = TabulatedEphemerisProvider({40115: fixture_table}).windows(unit, [wv3], start, end)
    via_table = TabulatedEphemerisProvider({40115: direct}).windows(unit, [wv3], start, end)
    assert via_adapter and len(via_adapter) == len(via_table)
    for a, b in zip(via_adapter, via_table):
        assert abs((a.rise - b.rise).total_seconds()) < 0.01
        assert abs((a.set - b.set).total_seconds()) < 0.01
