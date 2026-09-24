"""A unit on the WGS84 ellipsoid, and the elevation at which it sees a satellite."""

import datetime as dt

import numpy as np
import pytest
from skyfield.api import wgs84
from skyfield.framelib import itrs

from sentinel.passes.model import Unit
from sentinel.passes.topocentric import Site
from tests.omm_snapshot import TIMESCALE, satellite


def site(lat_deg, lon_deg, alt_m=0.0):
    return Site.from_unit(Unit("test", lat_deg, lon_deg, alt_m))


def test_the_equator_on_the_prime_meridian_is_one_semi_major_axis_along_x():
    assert site(0.0, 0.0).ecef_km == pytest.approx([6378.137, 0.0, 0.0], abs=1e-9)


def test_the_pole_is_one_semi_minor_axis_along_z():
    assert site(90.0, 0.0).ecef_km == pytest.approx([0.0, 0.0, 6356.752314245], abs=1e-9)


@pytest.mark.parametrize("lat,lon,alt_m", [(35.26, -116.68, 0.0), (49.44, 11.86, 420.0), (-33.87, 151.21, 58.0), (64.8, -147.7, 1500.0)])
def test_geodetic_to_earth_fixed_matches_skyfield(lat, lon, alt_m):
    expected = wgs84.latlon(lat, lon, elevation_m=alt_m).itrs_xyz.km
    assert site(lat, lon, alt_m).ecef_km == pytest.approx(expected, abs=1e-9)


def test_straight_up_is_ninety_degrees_and_along_the_ground_is_zero():
    here = site(35.26, -116.68)
    east = np.cross([0.0, 0.0, 1.0], here.up)
    overhead = here.ecef_km + 600.0 * here.up
    level = here.ecef_km + 600.0 * east / np.linalg.norm(east)
    below = here.ecef_km - 600.0 * here.up
    assert here.elevation_deg(np.array([overhead, level, below])) == pytest.approx([90.0, 0.0, -90.0], abs=1e-9)


def test_elevation_matches_skyfield_altaz_through_a_day():
    wv3 = satellite(40115)
    start = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
    times = TIMESCALE.from_datetimes([start + dt.timedelta(minutes=m) for m in range(0, 1440, 7)])
    here = Site.from_unit(Unit("ntc", 35.26, -116.68, 700.0))
    topos = wgs84.latlon(35.26, -116.68, elevation_m=700.0)
    ours = here.elevation_deg(wv3.at(times).frame_xyz(itrs).km.T)
    theirs = (wv3 - topos).at(times).altaz()[0].degrees
    assert ours == pytest.approx(theirs, abs=1e-6)
