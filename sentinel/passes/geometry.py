"""Geometry for overhead passes: field of regard, sunlight, timing pad.

Spherical Earth and a low-precision solar position are deliberate: pass
timing from element sets is good to about a second, and whether a unit is
lit only needs the sun's elevation to a fraction of a degree. The sun
formula is the Astronomical Almanac's low-precision one, checked against
JPL DE421 in tests/passes/test_geometry.py.
"""

from __future__ import annotations

import datetime as dt
import math

EARTH_RADIUS_KM = 6378.137
J2000 = dt.datetime(2000, 1, 1, 12, tzinfo=dt.UTC)
BASE_PAD_S = 60.0
PAD_PER_DAY_S = 30.0
STALE_AFTER_DAYS = 3.0


def min_elevation_deg(max_off_nadir_deg: float, altitude_km: float) -> float:
    """Lowest elevation, seen from the ground, at which a sensor pointing at
    most `max_off_nadir_deg` from nadir can see the observer.

    Law of sines in the Earth-centre / observer / satellite triangle:
        sin(off_nadir) = R / (R + h) * cos(elevation)
    A field of regard that reaches past the horizon is horizon-limited (0).
    """
    ratio = math.sin(math.radians(max_off_nadir_deg)) * (EARTH_RADIUS_KM + altitude_km) / EARTH_RADIUS_KM
    if ratio >= 1.0:
        return 0.0
    return math.degrees(math.acos(ratio))


def sun_elevation_deg(when: dt.datetime, lat_deg: float, lon_deg: float) -> float:
    """Geometric elevation of the sun (no refraction), degrees."""
    n = (when - J2000).total_seconds() / 86400.0
    mean_longitude = math.radians((280.460 + 0.9856474 * n) % 360)
    mean_anomaly = math.radians((357.528 + 0.9856003 * n) % 360)
    ecliptic_longitude = mean_longitude + math.radians(1.915 * math.sin(mean_anomaly) + 0.020 * math.sin(2 * mean_anomaly))
    obliquity = math.radians(23.439 - 0.0000004 * n)
    right_ascension = math.atan2(math.cos(obliquity) * math.sin(ecliptic_longitude), math.cos(ecliptic_longitude))
    declination = math.asin(math.sin(obliquity) * math.sin(ecliptic_longitude))
    sidereal = math.radians((280.46061837 + 360.98564736629 * n) % 360)
    hour_angle = sidereal + math.radians(lon_deg) - right_ascension
    lat = math.radians(lat_deg)
    sin_elevation = math.sin(lat) * math.sin(declination) + math.cos(lat) * math.cos(declination) * math.cos(hour_angle)
    return math.degrees(math.asin(sin_elevation))


def element_pad_s(age_days: float) -> float:
    """Timing margin for an element set of this age: 60 s plus 30 s a day.
    Element-set along-track error grows with age; the pad says so."""
    return BASE_PAD_S + PAD_PER_DAY_S * max(age_days, 0.0)
