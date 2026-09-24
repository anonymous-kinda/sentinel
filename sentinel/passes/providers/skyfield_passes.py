"""Passes of one satellite above a mask elevation, found with Skyfield.

Skyfield's `find_events` brackets each rise and set to half a second and
reports the bracket's later edge. A rise can therefore come up to 0.5 s
late. The 1 s brute-force oracle (tests/passes/test_oracle.py) caught a
second above the mask that fell 21 ms outside its window.

So each rise and set is bisected again, to a millisecond, and reported at
the end of its bracket that lies *below* the mask: before the true rise,
after the true set. A window therefore always contains the true pass and
is at most a millisecond wider at each end. It errs toward observed time,
never toward a gap.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable

import numpy as np
from skyfield.api import EarthSatellite
from skyfield.timelib import Time
from skyfield.toposlib import GeographicPosition

from ..elements import SECONDS_PER_DAY

RISE, CULMINATION, SET = 0, 1, 2
FINDER_BRACKET_DAYS = 1.0 / SECONDS_PER_DAY    # re-search a second either side of each finder event
REFINED_TO_DAYS = 0.001 / SECONDS_PER_DAY      # report rise and set to a millisecond

ElevationFn = Callable[[np.ndarray], np.ndarray]


@dataclasses.dataclass(frozen=True)
class Pass:
    rise: dt.datetime
    culmination: dt.datetime
    set: dt.datetime
    max_elevation_deg: float


def find_passes(
    satellite: EarthSatellite, observer: GeographicPosition, t0: Time, t1: Time, mask_deg: float
) -> list[Pass]:
    """Every whole pass (rise, culmination and set all inside [t0, t1])."""
    times, events = satellite.find_events(observer, t0, t1, altitude_degrees=mask_deg)
    if len(times) == 0:
        return []
    ts = t0.ts

    def elevation_deg(tt: np.ndarray) -> np.ndarray:
        return (satellite - observer).at(ts.tt_jd(tt)).altaz()[0].degrees

    rises, culminations, sets, peaks_deg = _whole_passes(times.tt, events, elevation_deg(times.tt))
    if len(rises) == 0:
        return []
    rises, sets = _refine(elevation_deg, mask_deg, rises, culminations, sets)

    def to_utc(tt: np.ndarray) -> list[dt.datetime]:
        return list(ts.tt_jd(tt).utc_datetime())

    return [
        Pass(rise, culmination, set_, float(peak_deg))
        for rise, culmination, set_, peak_deg in zip(to_utc(rises), to_utc(culminations), to_utc(sets), peaks_deg)
    ]


def _whole_passes(tt: np.ndarray, events: np.ndarray, elevations_deg: np.ndarray):
    """Group finder events into passes, keeping the highest culmination.
    A pass cut by the edge of the search (a set with no rise before it, a
    rise with no set after it) is dropped: the caller searches wide enough
    that such a pass cannot matter."""
    rises, culminations, sets, peaks_deg = [], [], [], []
    rise = None
    peaks: list[tuple[float, float]] = []
    for when, event, elevation in zip(tt, events, elevations_deg):
        if event == RISE:
            rise, peaks = when, []
        elif event == CULMINATION:
            peaks.append((float(elevation), when))
        elif rise is not None:
            peak_deg, culmination = max(peaks)
            rises.append(rise)
            culminations.append(culmination)
            sets.append(when)
            peaks_deg.append(peak_deg)
            rise = None
    return np.array(rises), np.array(culminations), np.array(sets), np.array(peaks_deg)


def _refine(elevation_deg: ElevationFn, mask_deg: float, rises, culminations, sets):
    """Rise brackets end at the culmination at the latest, set brackets
    start there at the earliest, so a short pass never folds into one
    bracket. Rises and sets are bisected together."""
    lo = np.concatenate((rises - FINDER_BRACKET_DAYS, np.maximum(sets - FINDER_BRACKET_DAYS, culminations)))
    hi = np.concatenate((np.minimum(rises + FINDER_BRACKET_DAYS, culminations), sets + FINDER_BRACKET_DAYS))
    edges = _below_mask_edge(elevation_deg, mask_deg, lo, hi)
    return edges[: len(rises)], edges[len(rises) :]


def _below_mask_edge(elevation_deg: ElevationFn, mask_deg: float, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Bisect brackets that straddle the mask, then return each one's
    below-mask end, which lies outside the pass."""
    lo_below = elevation_deg(lo) < mask_deg
    if np.any(lo_below == (elevation_deg(hi) < mask_deg)):
        raise RuntimeError("pass event bracket does not straddle the mask elevation")
    while np.max(hi - lo) > REFINED_TO_DAYS:
        mid = (lo + hi) / 2.0
        with_lo = (elevation_deg(mid) < mask_deg) == lo_below
        lo, hi = np.where(with_lo, mid, lo), np.where(with_lo, hi, mid)
    return np.where(lo_below, lo, hi)
