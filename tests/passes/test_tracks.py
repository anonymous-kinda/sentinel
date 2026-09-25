"""Ground tracks for the globe: Earth-fixed positions, visualization only.

The oracle is the raw SGP4 library (TEME), not Skyfield's frame code.
Without Earth-orientation data (offline), TEME and the Earth-fixed frame
differ only by a rotation about the pole, so the radius and the z
component must agree to well under a metre.
"""

import datetime as dt

import numpy as np
import pytest
from sgp4 import omm
from sgp4.api import Satrec, jday

from sentinel.passes.geometry import STALE_AFTER_DAYS
from sentinel.passes.tracks import MAX_ELEMENT_AGE, MAX_TRACK, STEP_S, ecef_track_m

from .exercise import START

WV3 = 40115


def teme_km(fields: dict, when: dt.datetime) -> np.ndarray:
    satrec = Satrec()
    omm.initialize(satrec, fields)
    jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute, when.second + when.microsecond / 1e6)
    error, r_km, _ = satrec.sgp4(jd, fr)
    assert error == 0
    return np.array(r_km)


@pytest.fixture(scope="module")
def track(snapshot):
    return ecef_track_m(snapshot[WV3], START, START + MAX_TRACK)


def test_thirty_minutes_at_the_stated_step_ends_included(track):
    assert STEP_S == 20
    assert len(track) == 91
    assert all(len(p) == 3 for p in track)


def test_positions_are_earth_fixed_metres_agreeing_with_raw_sgp4(track, snapshot):
    for index in (0, 45, 90):
        when = START + dt.timedelta(seconds=index * STEP_S)
        reference_m = teme_km(snapshot[WV3], when) * 1000.0
        position_m = np.array(track[index])
        assert np.linalg.norm(position_m) == pytest.approx(np.linalg.norm(reference_m), abs=1.0)
        assert position_m[2] == pytest.approx(reference_m[2], abs=1.0)


def test_consecutive_points_are_one_step_of_orbital_motion_apart(track):
    steps_m = np.linalg.norm(np.diff(np.array(track), axis=0), axis=1)
    assert np.all((steps_m > 20.0 * 6_500.0) & (steps_m < 20.0 * 8_000.0))


@pytest.mark.parametrize(
    "start,end",
    [
        (START, START + MAX_TRACK + dt.timedelta(seconds=1)),
        (START, START),
        (START, START - dt.timedelta(minutes=1)),
        (START.replace(tzinfo=None), START.replace(tzinfo=None) + dt.timedelta(minutes=5)),
    ],
)
def test_wrong_intervals_are_refused(snapshot, start, end):
    with pytest.raises(ValueError):
        ecef_track_m(snapshot[WV3], start, end)


def test_a_short_interval_still_has_both_ends(snapshot):
    track = ecef_track_m(snapshot[WV3], START, START + dt.timedelta(seconds=30))
    assert len(track) == 3, "start, one step, and the end"


# ------------------------------------------------ how far from the epoch
def epoch_of(element_set) -> dt.datetime:
    return dt.datetime.fromisoformat(element_set["EPOCH"]).replace(tzinfo=dt.UTC)


@pytest.mark.parametrize(
    "start_from_epoch",
    [
        dt.timedelta(0),
        MAX_ELEMENT_AGE - dt.timedelta(minutes=5),
        -MAX_ELEMENT_AGE,
    ],
    ids=["at-the-epoch", "ends-at-the-stale-line", "starts-at-the-line-before-the-epoch"],
)
def test_a_track_inside_the_usable_span_is_drawn(snapshot, start_from_epoch):
    start = epoch_of(snapshot[WV3]) + start_from_epoch
    assert len(ecef_track_m(snapshot[WV3], start, start + dt.timedelta(minutes=5))) == 16


@pytest.mark.parametrize(
    "start_from_epoch",
    [
        MAX_ELEMENT_AGE - dt.timedelta(minutes=4),
        -MAX_ELEMENT_AGE - dt.timedelta(minutes=1),
        dt.timedelta(days=30),
    ],
    ids=["ends-past-the-stale-line", "starts-before-the-line-before-the-epoch", "a-month-on"],
)
def test_a_track_beyond_the_usable_span_is_refused_with_the_reason(snapshot, start_from_epoch):
    """Past STALE_AFTER_DAYS the pass list flags a set stale; a track has no
    flag to carry, so it is not drawn: a precise-looking line from a set the
    module itself calls stale would claim more than the data can support."""
    start = epoch_of(snapshot[WV3]) + start_from_epoch
    with pytest.raises(ValueError, match=f"within {STALE_AFTER_DAYS:g} days of its epoch"):
        ecef_track_m(snapshot[WV3], start, start + dt.timedelta(minutes=5))


def test_the_usable_span_is_where_element_sets_are_not_yet_stale():
    assert dt.timedelta(days=STALE_AFTER_DAYS) == MAX_ELEMENT_AGE


def test_a_far_interval_is_refused_before_any_propagation(snapshot):
    """Year 9999 once came back as finite nonsense positions. Nor does an
    element set with a year-1 epoch overflow the check."""
    far = dt.datetime(9999, 12, 31, 23, 0, tzinfo=dt.UTC)
    ancient = {**snapshot[WV3], "EPOCH": "0001-01-01T00:00:00"}
    for element_set in (snapshot[WV3], ancient):
        with pytest.raises(ValueError, match="stale"):
            ecef_track_m(element_set, far, far + dt.timedelta(minutes=5))
