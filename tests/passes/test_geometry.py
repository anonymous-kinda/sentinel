"""Pass geometry: when can an imager see the unit, and is the unit lit?"""

import datetime as dt
import math

import numpy as np
import pytest

from sentinel.passes.geometry import (
    EARTH_RADIUS_KM,
    element_pad_s,
    min_elevation_deg,
    sun_elevation_deg,
)

# Sun elevation references: Skyfield 1.55 with JPL DE421 (apparent, no
# refraction), computed once outside this code and transcribed here.
SUN_REFERENCE = [
    ((2026, 9, 24, 19, 0), 35.26, -116.68, 52.928),    # NTC, local midday
    ((2026, 9, 24, 12, 0), 35.26, -116.68, -20.298),   # NTC, before dawn
    ((2026, 6, 21, 12, 0), 51.48, 0.0, 61.955),        # Greenwich, June solstice
    ((2026, 12, 21, 12, 0), 51.48, 0.0, 15.080),       # Greenwich, December solstice
    ((2026, 3, 20, 6, 0), 0.0, 90.0, 88.117),          # equator, near equinox
    ((2026, 9, 24, 9, 30), 49.44, 11.86, 36.042),      # Grafenwoehr, morning
    ((2026, 9, 24, 3, 0), -33.87, 151.21, 52.476),     # Sydney, afternoon
]


@pytest.mark.parametrize("when,lat,lon,expected", SUN_REFERENCE)
def test_sun_elevation_matches_the_jpl_ephemeris(when, lat, lon, expected):
    instant = dt.datetime(*when, tzinfo=dt.UTC)
    assert sun_elevation_deg(instant, lat, lon) == pytest.approx(expected, abs=0.1)


def off_nadir_by_construction(elevation_deg: float, altitude_km: float) -> float:
    """Independent check: place the observer, cast a ray at the elevation,
    intersect the orbit sphere, and measure the angle at the satellite."""
    observer = np.array([EARTH_RADIUS_KM, 0.0])
    e = math.radians(elevation_deg)
    ray = np.array([math.sin(e), math.cos(e)])               # local up is +x
    r = EARTH_RADIUS_KM + altitude_km
    b = 2 * observer @ ray
    distance = (-b + math.sqrt(b * b - 4 * (observer @ observer - r * r))) / 2
    satellite = observer + distance * ray
    to_nadir, to_observer = -satellite, observer - satellite
    cos_angle = to_nadir @ to_observer / (np.linalg.norm(to_nadir) * np.linalg.norm(to_observer))
    return math.degrees(math.acos(cos_angle))


@pytest.mark.parametrize("off_nadir,altitude_km", [(7.5, 705), (10.3, 786), (30, 694), (45, 617), (45, 514)])
def test_min_elevation_is_where_the_field_of_regard_meets_the_ground(off_nadir, altitude_km):
    elevation = min_elevation_deg(off_nadir, altitude_km)
    assert off_nadir_by_construction(elevation, altitude_km) == pytest.approx(off_nadir, abs=1e-6)


def test_nadir_only_means_overhead_only_and_a_wide_field_reaches_the_horizon():
    assert min_elevation_deg(0.0, 700) == pytest.approx(90.0)
    assert min_elevation_deg(80.0, 700) == 0.0


def test_the_timing_pad_grows_with_element_set_age():
    assert element_pad_s(0.0) == 60.0
    assert element_pad_s(2.0) == 120.0
