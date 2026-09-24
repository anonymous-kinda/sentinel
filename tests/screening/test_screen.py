"""Screening one primary against a catalogue, checked against brute force.

The oracle (tests/screening/conftest.py) samples range every second, then
every millisecond around each minimum, straight from Skyfield's SGP4 model.
Screening must find the same approaches, at the same TCA and miss distance,
through its pre-filter, 60 s sampling and Brent refinement.
"""

import datetime as dt
import time

import numpy as np
import pytest

from sentinel.screening.orbit import Orbit
from sentinel.screening.screen import ScreeningRefused, screen

from .conftest import WINDOW_START, WV3, brute_force_minima, crossing_object, range_km

THRESHOLD_KM = 10.0
TCA_TOLERANCE_S = 1e-3      # the oracle resolves TCA to 0.5 ms (measured: 0.49 ms)
MISS_TOLERANCE_KM = 1e-5    # and the miss distance to under a centimetre (measured: 6.6 mm)


def seconds_from_start(when: dt.datetime) -> float:
    return (when - WINDOW_START).total_seconds()


@pytest.mark.parametrize("raan_offset_deg", [30.0, 90.0, 170.0], ids=["4km_s", "11km_s", "head_on_15km_s"])
def test_every_approach_brute_force_finds_is_found_at_the_same_tca_and_miss(snapshot, raan_offset_deg):
    crosser = crossing_object(snapshot[WV3], raan_offset_deg)
    result = screen(WV3, {WV3: snapshot[WV3], crosser["NORAD_CAT_ID"]: crosser}, WINDOW_START, 24.0, THRESHOLD_KM)
    # A minimum within 10 m of the threshold could fall either side; widen the oracle to match only.
    oracle = brute_force_minima(snapshot[WV3], crosser, WINDOW_START, 24.0, THRESHOLD_KM + 0.01)
    assert len(oracle) >= 10, "the constructed orbits must meet repeatedly"

    found = [(seconds_from_start(a.tca), a.miss_distance_km) for a in result.approaches]
    for tca_s, miss_km in found:
        oracle_tca_s, oracle_miss_km = min(oracle, key=lambda o: abs(o[0] - tca_s))
        assert tca_s == pytest.approx(oracle_tca_s, abs=TCA_TOLERANCE_S)
        assert miss_km == pytest.approx(oracle_miss_km, abs=MISS_TOLERANCE_KM)
    for oracle_tca_s, oracle_miss_km in oracle:
        if oracle_miss_km <= THRESHOLD_KM - 0.01:
            assert any(abs(t - oracle_tca_s) <= TCA_TOLERANCE_S for t, _ in found), oracle_tca_s


def test_each_approach_names_both_objects_and_its_relative_speed(snapshot):
    crosser = crossing_object(snapshot[WV3], 170.0)
    result = screen(WV3, {WV3: snapshot[WV3], crosser["NORAD_CAT_ID"]: crosser}, WINDOW_START, 6.0, THRESHOLD_KM)
    first = result.approaches[0]
    assert (first.primary_id, first.secondary_id, first.secondary_name) == (WV3, 99115, "CROSSER 170 (TEST)")
    assert 14.0 < first.relative_speed_km_s < 15.5, "near head-on in LEO"
    assert [a.tca for a in result.approaches] == sorted(a.tca for a in result.approaches)
    assert all(WINDOW_START <= a.tca <= WINDOW_START + dt.timedelta(hours=6) for a in result.approaches)


def test_no_object_brute_force_sees_near_the_primary_is_missed_on_the_real_snapshot(snapshot):
    """10 s sampling bounds each true minimum from above; screening must reach at least as close."""
    threshold_km = 150.0
    result = screen(WV3, snapshot, WINDOW_START, 24.0, threshold_km)
    closest = {}
    for a in result.approaches:
        closest[a.secondary_id] = min(a.miss_distance_km, closest.get(a.secondary_id, np.inf))
    offsets_s = np.arange(0.0, 86400.0 + 1.0, 10.0)
    checked = 0
    for norad_id, fields in snapshot.items():
        if norad_id == WV3:
            continue
        sampled = range_km(snapshot[WV3], fields, WINDOW_START, offsets_s)
        interior = sampled[1:-1][(sampled[1:-1] <= sampled[:-2]) & (sampled[1:-1] < sampled[2:])]
        if interior.size and interior.min() <= threshold_km:
            checked += 1
            assert closest.get(norad_id, np.inf) <= interior.min() + 1e-9, norad_id
    assert checked >= 5, "the check must not be vacuous"


def test_a_real_day_for_worldview_3_has_nothing_within_5_km_and_says_how_much_it_screened(snapshot):
    started = time.perf_counter()
    result = screen(WV3, snapshot, WINDOW_START)
    elapsed_s = time.perf_counter() - started
    assert result.threshold_km == 5.0 and result.end - result.start == dt.timedelta(hours=24)
    assert result.approaches == ()
    assert result.secondaries == len(snapshot) - 1
    assert 0 < result.after_prefilter < result.secondaries, "the filter dropped some, not all"
    assert result.skipped == ()
    assert elapsed_s < 5.0, "one primary against 166 objects for a day (measured well under 1 s)"


def test_a_secondary_that_cannot_be_propagated_is_skipped_with_its_reason_and_the_rest_screened(snapshot):
    crosser = crossing_object(snapshot[WV3], 30.0)
    unreadable = {k: v for k, v in {**snapshot[WV3], "NORAD_CAT_ID": 99116}.items() if k != "OBJECT_ID"}
    decays_in_window = {**snapshot[WV3], "NORAD_CAT_ID": 99117, "ECCENTRICITY": 0.3, "MEAN_ANOMALY": 180.0}
    elements = {WV3: snapshot[WV3], 99115: crosser, 99116: unreadable, 99117: decays_in_window}
    result = screen(WV3, elements, WINDOW_START, 24.0, THRESHOLD_KM)
    assert {(s.norad_id, s.code) for s in result.skipped} == {
        (99116, "UNUSABLE_ELEMENTS"),
        (99117, "PROPAGATION_FAILED"),
    }
    assert result.approaches and {a.secondary_id for a in result.approaches} == {99115}


def test_an_unknown_primary_is_refused(snapshot):
    with pytest.raises(ScreeningRefused) as exc:
        screen(12345, snapshot, WINDOW_START)
    assert exc.value.code == "UNKNOWN_PRIMARY"


def test_a_primary_that_cannot_be_propagated_refuses_the_whole_screening(snapshot):
    elements = {**snapshot, WV3: {**snapshot[WV3], "ECCENTRICITY": 0.3, "MEAN_ANOMALY": 180.0}}
    with pytest.raises(ScreeningRefused) as exc:
        screen(WV3, elements, WINDOW_START)
    assert exc.value.code == "PROPAGATION_FAILED"


@pytest.mark.parametrize("kwargs", [{"hours": 0.0}, {"threshold_km": -1.0}])
def test_a_meaningless_window_or_threshold_raises_before_any_work(snapshot, kwargs):
    with pytest.raises(ValueError):
        screen(WV3, {WV3: snapshot[WV3]}, WINDOW_START, **kwargs)


def test_screening_uses_the_same_orbits_the_cdm_will(snapshot):
    """The miss the search reports is the distance between the states Orbit gives at that TCA."""
    crosser = crossing_object(snapshot[WV3], 90.0)
    [first, *_] = screen(WV3, {WV3: snapshot[WV3], 99115: crosser}, WINDOW_START, 6.0, THRESHOLD_KM).approaches
    r1, _ = Orbit.from_omm(snapshot[WV3]).gcrf_state_km(first.tca)
    r2, _ = Orbit.from_omm(crosser).gcrf_state_km(first.tca)
    assert np.linalg.norm(r2 - r1) == pytest.approx(first.miss_distance_km, abs=1e-6)
