"""SkyfieldProvider: local SGP4 pass prediction behind the PassProvider contract."""

import datetime as dt
import logging

import pytest

from sentinel.passes.elements import ElementSetError, epoch_utc, mean_altitude_km
from sentinel.passes.geometry import min_elevation_deg, sun_elevation_deg
from sentinel.passes.model import Imager, ImagerNotCovered
from sentinel.passes.providers.skyfield_local import EO_MIN_SUN_ELEVATION_DEG, SkyfieldProvider

from .exercise import END, EXERCISE_UNIT, START

ONE_SECOND = dt.timedelta(seconds=1)


@pytest.fixture(scope="module")
def provider(catalog_match):
    return SkyfieldProvider(catalog_match.element_sets)


@pytest.fixture(scope="module")
def day(provider, catalog_match):
    """Every catalogued imager over the 24 h exercise interval."""
    return provider.windows(EXERCISE_UNIT, catalog_match.imagers, START, END)


def longest_pass(windows):
    return max(windows, key=lambda w: w.set - w.rise)


def same_pass(a, b):
    return a.norad_id == b.norad_id and abs(a.rise - b.rise) <= ONE_SECOND and abs(a.set - b.set) <= ONE_SECOND


def test_the_provider_names_itself_on_every_window(provider, day):
    assert provider.name == "skyfield-local"
    assert day, "a day over the exercise unit has passes"
    assert {w.provider for w in day} == {"skyfield-local"}


def test_windows_are_sorted_by_rise_and_each_overlaps_the_interval(day):
    assert [w.rise for w in day] == sorted(w.rise for w in day)
    for w in day:
        assert w.rise < w.culmination < w.set
        assert w.rise <= END and w.set >= START


def test_the_mask_is_the_field_of_regard_at_the_element_sets_altitude(day, catalog_match):
    imagers = {i.norad_id: i for i in catalog_match.imagers}
    for w in day:
        altitude_km = mean_altitude_km(catalog_match.element_sets[w.norad_id])
        expected = min_elevation_deg(imagers[w.norad_id].max_off_nadir_deg, altitude_km)
        assert w.mask_elevation_deg == pytest.approx(expected)
        assert w.max_elevation_deg >= w.mask_elevation_deg


def test_element_age_is_measured_from_the_epoch_to_culmination(day, catalog_match):
    for w in day:
        epoch = epoch_utc(catalog_match.element_sets[w.norad_id])
        assert w.element_age_days == pytest.approx((w.culmination - epoch).total_seconds() / 86400.0)


def test_optical_passes_need_the_sun_ten_degrees_up_and_radar_passes_do_not(day):
    assert EO_MIN_SUN_ELEVATION_DEG == 10.0
    optical = [w for w in day if w.sensor == "EO"]
    radar = [w for w in day if w.sensor == "SAR"]
    for w in optical:
        lit = sun_elevation_deg(w.culmination, EXERCISE_UNIT.lat_deg, EXERCISE_UNIT.lon_deg) >= 10.0
        assert w.sunlit is lit
    assert {w.sunlit for w in optical} == {True, False}, "a day has lit and unlit optical passes"
    assert radar and all(w.sunlit is None for w in radar)


def test_a_pass_already_in_progress_at_start_keeps_its_true_rise(provider, by_name, day):
    imager = by_name["RADARSAT-2"]
    whole = longest_pass([w for w in day if w.norad_id == imager.norad_id])
    first, *_ = provider.windows(EXERCISE_UNIT, [imager], whole.culmination, whole.culmination + dt.timedelta(hours=1))
    assert same_pass(first, whole)
    assert first.rise < whole.culmination


def test_a_pass_still_up_at_end_keeps_its_true_set(provider, by_name, day):
    imager = by_name["RADARSAT-2"]
    whole = longest_pass([w for w in day if w.norad_id == imager.norad_id])
    *_, last = provider.windows(EXERCISE_UNIT, [imager], whole.rise - dt.timedelta(hours=1), whole.culmination)
    assert same_pass(last, whole)
    assert last.set > whole.culmination


def test_an_interval_inside_one_pass_returns_that_pass(provider, by_name, day):
    imager = by_name["RADARSAT-2"]
    whole = longest_pass([w for w in day if w.norad_id == imager.norad_id])
    (only,) = provider.windows(EXERCISE_UNIT, [imager], whole.rise + 10 * ONE_SECOND, whole.set - 10 * ONE_SECOND)
    assert same_pass(only, whole)


def test_a_pass_that_ended_before_the_interval_is_not_returned(provider, by_name, day):
    imager = by_name["RADARSAT-2"]
    whole = longest_pass([w for w in day if w.norad_id == imager.norad_id])
    after = provider.windows(EXERCISE_UNIT, [imager], whole.set + ONE_SECOND, whole.set + dt.timedelta(minutes=5))
    assert not any(same_pass(w, whole) for w in after)


def test_no_imagers_means_no_windows(provider):
    assert provider.windows(EXERCISE_UNIT, [], START, END) == []


def test_an_imager_without_a_matched_element_set_is_refused(provider):
    unknown = Imager(norad_id=99999, name="NOT CATALOGUED", sensor="EO", max_off_nadir_deg=30.0)
    with pytest.raises(ImagerNotCovered, match="missing"):
        provider.windows(EXERCISE_UNIT, [unknown], START, END)


def test_an_imager_whose_element_set_is_another_object_is_refused(provider):
    wrong = Imager(norad_id=40115, name="WORLDVIEW-2", sensor="EO", max_off_nadir_deg=40.0)
    with pytest.raises(ImagerNotCovered, match="name_mismatch"):
        provider.windows(EXERCISE_UNIT, [wrong], START, END)


def test_an_element_set_beyond_low_earth_orbit_is_refused(snapshot):
    """The search margin assumes a pass is shorter than an orbit, which
    only holds in low Earth orbit. GAOFEN-4 is geostationary."""
    geo = Imager(norad_id=41194, name="GAOFEN-4", sensor="EO", max_off_nadir_deg=5.0)
    provider = SkyfieldProvider({41194: snapshot[41194]})
    with pytest.raises(ElementSetError, match="low Earth orbit"):
        provider.windows(EXERCISE_UNIT, [geo], START, END)


@pytest.mark.parametrize(
    "start,end",
    [
        (START.replace(tzinfo=None), END),
        (START, END.replace(tzinfo=None)),
        (END, START),
        (START, START),
    ],
)
def test_a_naive_or_empty_interval_is_refused(provider, by_name, start, end):
    with pytest.raises(ValueError, match="interval"):
        provider.windows(EXERCISE_UNIT, [by_name["WORLDVIEW-3"]], start, end)


def test_a_stale_element_set_is_logged_once_per_imager(provider, by_name, caplog):
    caplog.set_level(logging.WARNING, logger="sentinel.passes.providers.skyfield_local")
    later = START + dt.timedelta(days=5)
    windows = provider.windows(EXERCISE_UNIT, [by_name["WORLDVIEW-3"]], later, later + dt.timedelta(days=1))
    assert windows and all(w.stale for w in windows)
    stale_records = [r for r in caplog.records if r.getMessage() == "Stale element set"]
    assert len(stale_records) == 1
    assert stale_records[0].fields["norad_id"] == 40115
