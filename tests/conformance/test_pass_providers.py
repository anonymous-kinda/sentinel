"""Conformance: what every PassProvider must do, whichever one it is (MOSA).

Each test runs once per entry in PROVIDER_FACTORIES. Adding a provider is
one line there (plus its factory in factories.py); it is then held to the
contract in sentinel/passes/model.py, including the overlap convention, and
to a brute-force Skyfield oracle: rise and set within 2 s, maximum
elevation within 0.1 deg.
"""

import datetime as dt

import pytest

from sentinel.passes.model import PassWindow

from . import factories
from .oracle import oracle_passes
from .scenario import SCENARIO, STRANGER

PROVIDER_FACTORIES = [
    pytest.param(factories.tabulated_from_skyfield, id="tabulated-ephemeris"),
]

RISE_SET_TOLERANCE_S = 2.0
MAX_ELEVATION_TOLERANCE_DEG = 0.1
CONVENTION_TOLERANCE_S = 0.1
UNIT, START, END, IMAGERS = SCENARIO.unit, SCENARIO.start, SCENARIO.end, SCENARIO.imagers


@pytest.fixture(scope="module", params=PROVIDER_FACTORIES)
def provider(request):
    return request.param(SCENARIO)


@pytest.fixture(scope="module")
def day(provider):
    windows = provider.windows(UNIT, IMAGERS, START, END)
    assert windows, "the scenario must produce windows or the suite proves nothing"
    return windows


@pytest.fixture(scope="module")
def oracle():
    return oracle_passes(SCENARIO)


def imager_of(window):
    return next(imager for imager in IMAGERS if imager.norad_id == window.norad_id)


def seconds_apart(a: dt.datetime, b: dt.datetime) -> float:
    return abs((a - b).total_seconds())


def same_pass(window, candidates):
    """The candidate window of the same satellite whose culmination is within a minute."""
    matches = [c for c in candidates if c.norad_id == window.norad_id and seconds_apart(c.culmination, window.culmination) < 60]
    assert len(matches) == 1, f"expected exactly one matching pass, found {len(matches)}"
    return matches[0]


# --- the shape of the answer ---------------------------------------------------

def test_every_window_is_a_pass_window_signed_by_its_provider(provider, day):
    assert all(isinstance(w, PassWindow) for w in day)
    assert {w.provider for w in day} == {provider.name}


def test_rise_precedes_culmination_precedes_set(day):
    assert all(w.rise < w.culmination < w.set for w in day)


def test_windows_are_sorted_by_rise(day):
    assert [w.rise for w in day] == sorted(w.rise for w in day)


def test_the_highest_elevation_clears_the_mask(day):
    assert all(w.max_elevation_deg >= w.mask_elevation_deg for w in day)


def test_radar_has_no_daylight_verdict_and_optical_always_has_one(day):
    for w in day:
        assert w.sensor == imager_of(w).sensor
        if w.sensor == "SAR":
            assert w.sunlit is None
        else:
            assert isinstance(w.sunlit, bool)


def test_an_imager_absent_from_the_data_gets_no_windows(provider, day):
    assert provider.windows(UNIT, [STRANGER], START, END) == []
    with_stranger = provider.windows(UNIT, [*IMAGERS, STRANGER], START, END)
    assert [(w.norad_id, w.rise) for w in with_stranger] == [(w.norad_id, w.rise) for w in day]


# --- the overlap convention (sentinel/passes/model.py) -------------------------

def test_every_window_overlaps_the_interval(day):
    assert all(w.rise <= END and w.set >= START for w in day)


def test_a_pass_already_up_at_the_start_keeps_its_true_rise(provider, day):
    for w in day:
        clipped = provider.windows(UNIT, [imager_of(w)], w.culmination, w.culmination + dt.timedelta(minutes=1))
        got = same_pass(w, clipped)
        assert got.rise < w.culmination
        assert seconds_apart(got.rise, w.rise) < CONVENTION_TOLERANCE_S
        assert seconds_apart(got.set, w.set) < CONVENTION_TOLERANCE_S


def test_a_pass_still_up_at_the_end_keeps_its_true_set(provider, day):
    for w in day:
        clipped = provider.windows(UNIT, [imager_of(w)], w.culmination - dt.timedelta(minutes=1), w.culmination)
        got = same_pass(w, clipped)
        assert got.set > w.culmination
        assert seconds_apart(got.rise, w.rise) < CONVENTION_TOLERANCE_S
        assert seconds_apart(got.set, w.set) < CONVENTION_TOLERANCE_S


def test_an_interval_between_passes_has_no_windows(provider, day):
    for w in day:
        after = w.set + dt.timedelta(seconds=1)
        gap = provider.windows(UNIT, [imager_of(w)], after, after + dt.timedelta(seconds=1))
        assert gap == []


# --- accuracy against the brute-force oracle -----------------------------------

def test_the_same_passes_as_the_oracle_no_more_no_fewer(day, oracle):
    assert oracle, "the oracle must see passes or the comparison proves nothing"
    for expected in oracle:
        same_pass(expected, day)          # exactly one window for each oracle pass
    assert len(day) == len(oracle)        # and none it did not see


def test_rise_and_set_agree_with_the_oracle_within_two_seconds(day, oracle):
    for expected in oracle:
        got = same_pass(expected, day)
        assert seconds_apart(got.rise, expected.rise) < RISE_SET_TOLERANCE_S
        assert seconds_apart(got.set, expected.set) < RISE_SET_TOLERANCE_S


def test_maximum_elevation_agrees_with_the_oracle_within_a_tenth_of_a_degree(day, oracle):
    for expected in oracle:
        got = same_pass(expected, day)
        assert abs(got.max_elevation_deg - expected.max_elevation_deg) < MAX_ELEVATION_TOLERANCE_DEG
