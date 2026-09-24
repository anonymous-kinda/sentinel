"""Oracle: the provider against brute force.

Samples each imager's elevation at the exercise unit every second for 24 h,
using Skyfield directly (no event finder), and checks the provider's
windows against the samples:

- every sampled second above the mask falls inside a returned window;
- each run of samples above the mask is one window, with rise and set
  within 2 s (the samples are 1 s apart);
- the peak sampled elevation matches the window's maximum elevation.
"""

import dataclasses
import datetime as dt

import numpy as np
import pytest
from skyfield.api import EarthSatellite, load, wgs84

from sentinel.passes.elements import mean_altitude_km
from sentinel.passes.geometry import min_elevation_deg
from sentinel.passes.providers.skyfield_local import SkyfieldProvider

from .exercise import END, EXERCISE_UNIT, START

TOLERANCE = dt.timedelta(seconds=2)

# A spread of masks (13 to 82 deg) and altitudes (380 to 790 km), EO and SAR.
ORACLE_IMAGERS = ["WORLDVIEW-3", "RADARSAT-2", "TERRASAR-X", "SENTINEL-1A", "SKYSAT-C11", "LANDSAT 8"]


@dataclasses.dataclass(frozen=True)
class Run:
    """Consecutive seconds above the mask, as sample indices."""

    first: int
    last: int
    peak_deg: float


@pytest.fixture(scope="module")
def sample_times():
    """One Time array for every imager: Skyfield caches its Earth-rotation
    matrices on it, which is most of the cost of sampling a day."""
    timescale = load.timescale(builtin=True)
    seconds = np.arange(int((END - START).total_seconds()) + 1)
    return timescale.utc(START.year, START.month, START.day, START.hour, START.minute, START.second + seconds)


def sampled_elevations_deg(sample_times, element_set):
    satellite = EarthSatellite.from_omm(sample_times.ts, element_set)
    observer = wgs84.latlon(EXERCISE_UNIT.lat_deg, EXERCISE_UNIT.lon_deg, elevation_m=EXERCISE_UNIT.alt_m)
    return (satellite - observer).at(sample_times).altaz()[0].degrees


def runs_above(elevations_deg, mask_deg):
    above = elevations_deg >= mask_deg
    edges = np.flatnonzero(np.diff(above.astype(np.int8)))
    starts = [0] if above[0] else []
    starts += [i + 1 for i in edges if not above[i]]
    ends = [i for i in edges if above[i]]
    ends += [len(above) - 1] if above[-1] else []
    return [Run(a, b, float(elevations_deg[a : b + 1].max())) for a, b in zip(starts, ends)]


def at(index: int) -> dt.datetime:
    return START + dt.timedelta(seconds=int(index))


@pytest.mark.parametrize("name", ORACLE_IMAGERS)
def test_windows_agree_with_one_second_brute_force(name, by_name, catalog_match, sample_times):
    imager = by_name[name]
    element_set = catalog_match.element_sets[imager.norad_id]
    mask_deg = min_elevation_deg(imager.max_off_nadir_deg, mean_altitude_km(element_set))
    windows = SkyfieldProvider(catalog_match.element_sets).windows(EXERCISE_UNIT, [imager], START, END)
    elevations_deg = sampled_elevations_deg(sample_times, element_set)
    runs = runs_above(elevations_deg, mask_deg)

    # Every sampled second above the mask is inside a returned window.
    for index in np.flatnonzero(elevations_deg >= mask_deg):
        instant = at(int(index))
        assert any(w.rise <= instant <= w.set for w in windows), f"{name}: {instant} above mask, no window"

    # One window per run; interior runs pin rise and set to within 2 s.
    assert len(windows) == len(runs), f"{name}: {len(windows)} windows, {len(runs)} sampled runs"
    for window, run in zip(windows, runs):
        if run.first > 0:
            assert abs(window.rise - at(run.first)) <= TOLERANCE, name
        else:
            assert window.rise <= START, "a pass in progress at start keeps its true, earlier rise"
        if run.last < len(elevations_deg) - 1:
            assert abs(window.set - at(run.last)) <= TOLERANCE, name
        else:
            assert window.set >= END, "a pass still up at end keeps its true, later set"
        assert window.max_elevation_deg == pytest.approx(run.peak_deg, abs=0.05)
        assert window.mask_elevation_deg == pytest.approx(mask_deg)


# Landsat 8 (7.5 deg field of regard) never reaches this unit in this day;
# the brute-force test above confirms it.
@pytest.mark.parametrize("name", [n for n in ORACLE_IMAGERS if n != "LANDSAT 8"])
def test_each_window_contains_the_true_pass_to_a_millisecond(name, by_name, catalog_match):
    """Rise and set sit just below the mask, and 2 ms inside them the
    imager is above it: the window holds the whole pass and barely more."""
    imager = by_name[name]
    element_set = catalog_match.element_sets[imager.norad_id]
    windows = SkyfieldProvider(catalog_match.element_sets).windows(EXERCISE_UNIT, [imager], START, END)
    assert windows, name
    timescale = load.timescale(builtin=True)
    satellite = EarthSatellite.from_omm(timescale, element_set)
    observer = wgs84.latlon(EXERCISE_UNIT.lat_deg, EXERCISE_UNIT.lon_deg, elevation_m=EXERCISE_UNIT.alt_m)
    inside = dt.timedelta(milliseconds=2)
    instants = [t for w in windows for t in (w.rise, w.rise + inside, w.set - inside, w.set)]
    elevations_deg = (satellite - observer).at(timescale.from_datetimes(instants)).altaz()[0].degrees
    for i, window in enumerate(windows):
        at_rise, after_rise, before_set, at_set = elevations_deg[4 * i : 4 * i + 4]
        assert at_rise < window.mask_elevation_deg <= after_rise, name
        assert at_set < window.mask_elevation_deg <= before_set, name


def test_the_oracle_saw_passes_worth_checking(by_name, catalog_match):
    """Guard against a vacuous oracle: the chosen imagers pass overhead."""
    provider = SkyfieldProvider(catalog_match.element_sets)
    windows = provider.windows(EXERCISE_UNIT, [by_name[n] for n in ORACLE_IMAGERS], START, END)
    assert len(windows) >= 10
    assert {w.sensor for w in windows} == {"EO", "SAR"}
