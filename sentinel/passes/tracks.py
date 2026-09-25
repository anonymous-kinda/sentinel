"""A satellite's ground track for the console globe: visualization only.

Earth-fixed (ITRS) positions in metres, every STEP_S seconds, from SGP4
through Skyfield's bundled timescale (no ephemeris, no network). Nothing
here decides a pass or a gap; those come from the provider and gaps.py.
Intervals are capped at MAX_TRACK, which is longer than any LEO pass.

A track is drawn only within MAX_ELEMENT_AGE (STALE_AFTER_DAYS) of its
element set's epoch. A pass answer keeps using an older set and flags it
stale, because a cut-off edge still needs an answer; a track has no flag
to carry, and far from the epoch SGP4 returns finite positions that mean
nothing. Beyond the span it raises ValueError with the reason.
"""

from __future__ import annotations

import datetime as dt
import functools

import numpy as np
from skyfield.api import EarthSatellite, load
from skyfield.framelib import itrs
from skyfield.timelib import Timescale

from .elements import ElementSet, ElementSetError, epoch_utc
from .geometry import STALE_AFTER_DAYS
from .interval import require_interval

STEP_S = 20
MAX_TRACK = dt.timedelta(minutes=30)
MAX_ELEMENT_AGE = dt.timedelta(days=STALE_AFTER_DAYS)


@functools.cache
def _timescale() -> Timescale:
    return load.timescale(builtin=True)


def ecef_track_m(element_set: ElementSet, start: dt.datetime, end: dt.datetime) -> list[list[float]]:
    require_interval(start, end)
    if end - start > MAX_TRACK:
        raise ValueError(f"a track covers at most {MAX_TRACK.total_seconds() / 60:g} minutes")
    _require_usable_span(element_set, start, end)
    ts = _timescale()
    satellite = EarthSatellite.from_omm(ts, element_set)
    positions_m = satellite.at(ts.from_datetimes(_sample_times(start, end))).frame_xyz(itrs).m
    if not np.all(np.isfinite(positions_m)):
        raise ElementSetError(f"object {element_set['NORAD_CAT_ID']}: SGP4 cannot propagate over this interval")
    return positions_m.T.tolist()


def _require_usable_span(element_set: ElementSet, start: dt.datetime, end: dt.datetime) -> None:
    """A track is drawn only where its element set is not stale: within
    MAX_ELEMENT_AGE of the epoch, either side, since SGP4's error grows both
    ways. Measured as differences, so no epoch can overflow the check."""
    epoch = epoch_utc(element_set)
    if start - epoch < -MAX_ELEMENT_AGE or end - epoch > MAX_ELEMENT_AGE:
        raise ValueError(
            "the element set is stale over this interval: a track is drawn only within "
            f"{STALE_AFTER_DAYS:g} days of its epoch ({epoch.isoformat()})"
        )


def _sample_times(start: dt.datetime, end: dt.datetime) -> list[dt.datetime]:
    """Every STEP_S from start, and the end itself."""
    span_s = (end - start).total_seconds()
    offsets_s = np.arange(0.0, span_s, STEP_S).tolist() + [span_s]
    return [start + dt.timedelta(seconds=offset) for offset in offsets_s]
