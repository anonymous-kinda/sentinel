"""Each screened approach becomes a DERIVED CDM with no covariance.

A Pc is then refused by construction: the CDM goes through the same
parse, validate and assess path as any other, and the engine's existing
NO_COVARIANCE gate declines it. There is no screening branch in the engine.
"""

import asyncio
import datetime as dt
import hashlib
import re

import numpy as np
import pytest
from skyfield.api import EarthSatellite, load

from sentinel.bus import InProcessBus
from sentinel.cdm import emit, parse, validate
from sentinel.cdm.model import POSITION_COVARIANCE_KEYS
from sentinel.clock import FixedClock
from sentinel.conjunction.service import ConjunctionService
from sentinel.conjunction.store import ConjunctionStore
from sentinel.passes.element_store import canonical_bytes
from sentinel.screening.derived_cdm import (
    DEMONSTRATION_COMMENT,
    ORIGINATOR,
    derived_cdm,
    derived_cdms,
)
from sentinel.screening.screen import screen

from .conftest import WINDOW_START, WV3, crossing_object

CREATED = WINDOW_START + dt.timedelta(minutes=5)
# Every 508.0-B-1 covariance keyword (CR_R ... CSRP_SRP), and COVARIANCE_METHOD.
COVARIANCE_KEY = re.compile(r"^C(R|T|N|RDOT|TDOT|NDOT|DRG|SRP)_|^COVARIANCE_METHOD$")
# The CDM states sit at the TCA rounded to the millisecond; at ~11 km/s that
# moves the separation by millimetres, never more than a few centimetres.
ROUNDING_TOLERANCE_M = 0.05


@pytest.fixture(scope="module")
def screened(snapshot):
    elements = {WV3: snapshot[WV3], 99115: crossing_object(snapshot[WV3], 90.0)}
    return screen(WV3, elements, WINDOW_START, 6.0, 10.0), elements


@pytest.fixture(scope="module")
def message(screened):
    result, elements = screened
    return derived_cdm(result, result.approaches[0], elements, CREATED)


def state_km(section, keys):
    return np.array([section.number(k) for k in keys])


def test_it_is_a_cdm_that_says_what_it_is_and_carries_no_pc(message):
    assert parse(emit(message)) == message
    assert message.originator == ORIGINATOR == "SENTINEL-SCREENING"
    assert DEMONSTRATION_COMMENT == "Demonstration mode: element-set geometry only; no probability of collision (ADR-002)"
    assert DEMONSTRATION_COMMENT in message.preamble.comments()
    assert message.collision_probability is None and message.collision_probability_method is None
    assert "COLLISION_PROBABILITY" not in emit(message)
    assert message.creation_date == CREATED


def test_neither_object_carries_any_covariance_and_validation_says_so(message):
    for section in message.objects:
        assert all(section.get(key) is None for key in POSITION_COVARIANCE_KEYS)
        assert [f.key for f in section.fields() if COVARIANCE_KEY.match(f.key)] == []
    warnings = validate(message)
    assert {(w.code, w.object_index) for w in warnings} == {("COVARIANCE_ABSENT", 0), ("COVARIANCE_ABSENT", 1)}


def test_the_objects_are_named_and_their_element_sets_traceable(message, screened):
    _, elements = screened
    assert [message.object_designator(i) for i in (0, 1)] == ["40115", "99115"]
    assert message.object_name(0).startswith("WORLDVIEW-3") and message.object_name(1) == "CROSSER 90 (TEST)"
    assert message.objects[0].text("INTERNATIONAL_DESIGNATOR") == "2014-048A"
    for section, norad_id in zip(message.objects, (WV3, 99115)):
        sha16 = hashlib.sha256(canonical_bytes(elements[norad_id])).hexdigest()[:16]
        assert any(sha16 in c and elements[norad_id]["EPOCH"][:23] in c for c in section.comments())


def test_the_states_are_skyfield_gcrs_at_the_millisecond_tca(message, screened):
    result, elements = screened
    approach = result.approaches[0]
    assert abs((message.tca - approach.tca).total_seconds()) <= 0.0005
    assert message.tca.microsecond % 1000 == 0
    ts = load.timescale(builtin=True)
    for section, norad_id in zip(message.objects, (WV3, 99115)):
        assert section.text("REF_FRAME") == "GCRF"
        at = EarthSatellite.from_omm(ts, elements[norad_id]).at(ts.from_datetime(message.tca))
        np.testing.assert_allclose(state_km(section, ("X", "Y", "Z")), at.position.km, atol=1e-6)
        np.testing.assert_allclose(state_km(section, ("X_DOT", "Y_DOT", "Z_DOT")), at.velocity.km_per_s, atol=1e-9)


def test_the_header_miss_and_speed_describe_the_states_and_the_screened_approach(message, screened):
    result, _ = screened
    approach = result.approaches[0]
    r1, r2 = (state_km(s, ("X", "Y", "Z")) for s in message.objects)
    v1, v2 = (state_km(s, ("X_DOT", "Y_DOT", "Z_DOT")) for s in message.objects)
    assert message.miss_distance_m == pytest.approx(np.linalg.norm(r2 - r1) * 1000.0, abs=0.002)
    assert message.miss_distance_m == pytest.approx(approach.miss_distance_km * 1000.0, abs=ROUNDING_TOLERANCE_M)
    assert message.relative_speed_m_s == pytest.approx(np.linalg.norm(v2 - v1) * 1000.0, abs=0.002)
    assert message.relative_speed_m_s == pytest.approx(approach.relative_speed_km_s * 1000.0, abs=0.01)
    assert message.preamble.text("START_SCREEN_PERIOD").startswith("2026-09-24T06:00:00")
    assert message.preamble.text("STOP_SCREEN_PERIOD").startswith("2026-09-24T12:00:00")


def test_every_approach_becomes_one_cdm_with_its_own_message_id(screened):
    result, elements = screened
    messages = derived_cdms(result, elements, CREATED)
    assert len(messages) == len(result.approaches) >= 2
    assert len({m.message_id for m in messages}) == len(messages)


def ingest(raw: bytes, data_class: str):
    service = ConjunctionService(ConjunctionStore(), InProcessBus(), FixedClock(CREATED))
    outcome = asyncio.run(service.ingest(raw, "screening", data_class))
    return service, outcome


def test_ingested_as_derived_the_engine_refuses_a_pc_for_want_of_covariance(message, screened):
    result, _ = screened
    approach = result.approaches[0]
    service, outcome = ingest(emit(message).encode(), "DERIVED")
    assert outcome.status == "accepted", outcome
    summary = service.event_summary(outcome.event_id)
    assessment = summary["assessment"]
    assert summary["data_class"] == "DERIVED"
    assert assessment["method"] == "REFUSED" and assessment["refusal_reason"] == "NO_COVARIANCE"
    assert assessment["pc"] is None and assessment["pc_max"] is None
    assert assessment["miss_distance_m"] == pytest.approx(approach.miss_distance_km * 1000.0, abs=ROUNDING_TOLERANCE_M)
    assert assessment["relative_speed_m_s"] == pytest.approx(approach.relative_speed_km_s * 1000.0, abs=0.01)


def test_a_screening_cdm_stays_derived_however_it_arrives(message):
    """An API upload is ingested as REAL; the originator marks it DERIVED, as SENTINEL-EXERCISE marks EXERCISE."""
    service, outcome = ingest(emit(message).encode(), "REAL")
    assert service.event_summary(outcome.event_id)["data_class"] == "DERIVED"
