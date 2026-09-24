"""A brute-force pass oracle: Skyfield's own topocentric elevation, every second.

Deliberately naive and independent of every provider: SGP4 through
Skyfield's altaz (no tables, no interpolation, no root finder), sampled at
1 s across the day plus a margin. Crossings are placed by linear
interpolation between the two seconds that straddle the mask, and the peak
by sampling every 0.01 s around the highest second, so the oracle's own
error is milliseconds and a comparison measures the provider.

The mask follows the pass-module convention: min_elevation_deg at the
satellite's altitude above the spherical Earth (radius - EARTH_RADIUS_KM)
at culmination.
"""

import dataclasses
import datetime as dt

import numpy as np
from skyfield.api import EarthSatellite, wgs84

from sentinel.passes.geometry import EARTH_RADIUS_KM, min_elevation_deg
from tests.omm_snapshot import TIMESCALE, omm_records

from .scenario import Scenario

MARGIN_S = 1800


@dataclasses.dataclass(frozen=True)
class OraclePass:
    norad_id: int
    rise: dt.datetime
    culmination: dt.datetime
    set: dt.datetime
    max_elevation_deg: float
    mask_elevation_deg: float


def _times(start: dt.datetime, seconds: np.ndarray):
    return TIMESCALE.utc(start.year, start.month, start.day, start.hour, start.minute, start.second + seconds)


def _crossing_s(seconds: np.ndarray, elevation: np.ndarray, below: int, toward: int, mask_deg: float) -> float:
    """Linear interpolation between sample `below` (under the mask) and its
    neighbour one step `toward` the pass (+1 for a rise, -1 for a set)."""
    above = below + toward
    fraction = (mask_deg - elevation[below]) / (elevation[above] - elevation[below])
    return float(seconds[below] + fraction * (seconds[above] - seconds[below]))


def _peak(satellite, topos, start: dt.datetime, second: float) -> tuple[float, float, float]:
    """Culmination second, elevation there, and radius there, from 0.01 s samples around `second`."""
    fine = second + np.arange(-1.0, 1.0 + 1e-9, 0.01)
    times = _times(start, fine)
    elevation = (satellite - topos).at(times).altaz()[0].degrees
    best = int(np.argmax(elevation))
    radius_km = float(satellite.at(times[best]).distance().km)
    return float(fine[best]), float(elevation[best]), radius_km


def oracle_passes(scenario: Scenario) -> list[OraclePass]:
    span_s = (scenario.end - scenario.start).total_seconds()
    seconds = np.arange(-MARGIN_S, span_s + MARGIN_S + 1, 1.0)
    times = _times(scenario.start, seconds)
    unit = scenario.unit
    topos = wgs84.latlon(unit.lat_deg, unit.lon_deg, elevation_m=unit.alt_m)
    found = []
    for imager in scenario.imagers:
        satellite = EarthSatellite.from_omm(TIMESCALE, omm_records()[imager.norad_id])
        elevation = (satellite - topos).at(times).altaz()[0].degrees
        peaks = np.flatnonzero((elevation[1:-1] > elevation[:-2]) & (elevation[1:-1] >= elevation[2:])) + 1
        for k in peaks:
            culmination_s, top_deg, radius_km = _peak(satellite, topos, scenario.start, seconds[k])
            mask_deg = min_elevation_deg(imager.max_off_nadir_deg, radius_km - EARTH_RADIUS_KM)
            if top_deg < mask_deg:
                continue
            under = np.flatnonzero(elevation < mask_deg)
            before, after = under[under < k], under[under > k]
            assert before.size and after.size, "oracle margin too short for this pass"
            rise_s = _crossing_s(seconds, elevation, int(before[-1]), +1, mask_deg)
            set_s = _crossing_s(seconds, elevation, int(after[0]), -1, mask_deg)
            if rise_s > span_s or set_s < 0.0:
                continue
            at = scenario.start
            found.append(OraclePass(
                imager.norad_id, _after(at, rise_s), _after(at, culmination_s), _after(at, set_s), top_deg, mask_deg,
            ))
    return found


def _after(start: dt.datetime, seconds: float) -> dt.datetime:
    return start + dt.timedelta(seconds=seconds)
