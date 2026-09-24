"""Pass provider from tabulated Earth-fixed ephemerides (CCSDS OEM, a vendor feed).

The second, independent implementation of the PassProvider contract. The
first propagates element sets with SGP4. This one never propagates: it
interpolates a table someone else produced, so the two agree only if the
contract, not the code, is shared (MOSA). The conformance suite holds both
to the same behaviour and to a brute-force oracle.

How a pass is found, in seconds from the table start:
  1. sample the unit's elevation every COARSE_STEP_S over the requested
     interval plus SEARCH_MARGIN_S either side, clipped to the table;
  2. each local maximum is a candidate culmination, refined by maximising
     the interpolated elevation (bounded Brent, to TIME_TOLERANCE_S);
  3. the mask is the elevation at which the imager's field of regard meets
     the ground, from min_elevation_deg at the altitude of culmination
     (interpolated radius minus EARTH_RADIUS_KM, the same spherical model
     min_elevation_deg is derived in);
  4. rise and set are where the elevation crosses the mask, bracketed by the
     coarse samples and refined by Brent's method to TIME_TOLERANCE_S.

It never extrapolates. A pass whose rise or set lies outside the table is
not reported; a warning says so. So does an interval the table does not
cover.

element_age_days is the age of the ephemeris product at culmination
(culmination - table.created). A predicted ephemeris is only as fresh as the
orbit determination it was propagated from, and its error grows with time
since then, exactly as an element set's does with time since its epoch.
The product's creation date is the best stand-in for that orbit
determination the formats carry: the true orbit-determination epoch is at
or before it, so the reported age is a lower bound. The same element_pad_s
then widens the window as the product ages. For a table derived from an
element set (sentinel.ephemeris.tabulate), `created` is the element-set
epoch, and the age equals the SGP4 provider's.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from collections.abc import Iterator, Mapping, Sequence

import numpy as np
from scipy.optimize import brentq, minimize_scalar

from sentinel.ephemeris.interpolate import LagrangeInterpolator
from sentinel.ephemeris.table import EphemerisRejected, StateTable
from sentinel.obs import get_logger

from ..geometry import (
    EARTH_RADIUS_KM,
    EO_MIN_SUN_ELEVATION_DEG,
    min_elevation_deg,
    sun_elevation_deg,
)
from ..model import Imager, ImagerNotCovered, PassWindow, Unit
from ..topocentric import Site

log = get_logger(__name__)

COARSE_STEP_S = 30.0
SEARCH_MARGIN_S = 1800.0      # longer than any LEO pass, so rises before the interval are found
TIME_TOLERANCE_S = 1.0e-3


@dataclasses.dataclass(frozen=True)
class _Pass:
    """One pass above the mask, in seconds from the table start. A rise or
    set of None lies beyond the searched span."""

    rise_s: float | None
    culmination_s: float
    set_s: float | None
    max_elevation_deg: float
    mask_elevation_deg: float

    def overlaps(self, start_s: float, end_s: float) -> bool:
        return (self.rise_s is None or self.rise_s <= end_s) and (self.set_s is None or self.set_s >= start_s)

    @property
    def complete(self) -> bool:
        return self.rise_s is not None and self.set_s is not None


def _grid(lo_s: float, hi_s: float) -> np.ndarray:
    intervals = max(math.ceil((hi_s - lo_s) / COARSE_STEP_S), 1)
    return np.linspace(lo_s, hi_s, intervals + 1)


def _peaks(elevations: np.ndarray) -> list[int]:
    """Local maxima, plus either end of the span if the elevation is still
    rising towards it (the pass may peak beyond)."""
    if len(elevations) < 2:
        return []
    middle = elevations[1:-1]
    inner = np.flatnonzero((middle > elevations[:-2]) & (middle >= elevations[2:])) + 1
    ends = [0] if elevations[0] > elevations[1] else []
    if elevations[-1] > elevations[-2]:
        ends.append(len(elevations) - 1)
    return [*ends, *inner.tolist()]


class _PassSearch:
    """Passes of one tabulated object over one site, for one field of regard."""

    def __init__(self, track: LagrangeInterpolator, site: Site, max_off_nadir_deg: float):
        self._track = track
        self._site = site
        self._max_off_nadir_deg = max_off_nadir_deg

    def elevation_deg(self, time_s: float) -> float:
        return float(self._site.elevation_deg(self._track.positions_km([time_s]))[0])

    def passes(self, lo_s: float, hi_s: float) -> Iterator[_Pass]:
        grid = _grid(lo_s, hi_s)
        elevations = self._site.elevation_deg(self._track.positions_km(grid))
        for index in _peaks(elevations):
            found = self._pass_at(grid, elevations, index)
            if found is not None:
                yield found

    def _pass_at(self, grid: np.ndarray, elevations: np.ndarray, index: int) -> _Pass | None:
        culmination_s, top_deg = self._culmination(grid, elevations, index)
        mask_deg = min_elevation_deg(self._max_off_nadir_deg, self._altitude_km(culmination_s))
        if top_deg < mask_deg:
            return None
        rise_s = self._crossing(grid, elevations, culmination_s, mask_deg, before=True)
        set_s = self._crossing(grid, elevations, culmination_s, mask_deg, before=False)
        return _Pass(rise_s, culmination_s, set_s, top_deg, mask_deg)

    def _culmination(self, grid: np.ndarray, elevations: np.ndarray, index: int) -> tuple[float, float]:
        if index in (0, len(grid) - 1):
            return float(grid[index]), float(elevations[index])
        best = minimize_scalar(
            lambda time_s: -self.elevation_deg(time_s),
            bounds=(grid[index - 1], grid[index + 1]),
            method="bounded",
            options={"xatol": TIME_TOLERANCE_S},
        )
        return float(best.x), float(-best.fun)

    def _altitude_km(self, time_s: float) -> float:
        return float(np.linalg.norm(self._track.positions_km([time_s])[0])) - EARTH_RADIUS_KM

    def _crossing(
        self, grid: np.ndarray, elevations: np.ndarray, culmination_s: float, mask_deg: float, before: bool
    ) -> float | None:
        """The mask crossing on one side of culmination, or None if the
        searched span ends first. The last coarse sample below the mask
        brackets it."""
        side = grid < culmination_s if before else grid > culmination_s
        below = np.flatnonzero(side & (elevations < mask_deg))
        if below.size == 0:
            return None
        outside_s = float(grid[below[-1] if before else below[0]])
        low_s, high_s = sorted((outside_s, culmination_s))
        return float(brentq(lambda time_s: self.elevation_deg(time_s) - mask_deg, low_s, high_s, xtol=TIME_TOLERANCE_S))


class TabulatedEphemerisProvider:
    """PassProvider over StateTables keyed by catalog number."""

    name = "tabulated-ephemeris"

    def __init__(self, tables: Mapping[int, StateTable], min_sun_elevation_deg: float = EO_MIN_SUN_ELEVATION_DEG):
        for norad_id, table in tables.items():
            if table.norad_id != norad_id:
                raise EphemerisRejected("NORAD_ID_MISMATCH", f"table for {table.norad_id} filed under {norad_id}")
        self._tracks = {norad_id: LagrangeInterpolator(table) for norad_id, table in tables.items()}
        self.min_sun_elevation_deg = min_sun_elevation_deg

    def windows(
        self, unit: Unit, imagers: Sequence[Imager], start: dt.datetime, end: dt.datetime
    ) -> list[PassWindow]:
        site = Site.from_unit(unit)
        found: list[PassWindow] = []
        for imager in imagers:
            track = self._tracks.get(imager.norad_id)
            if track is None:
                raise ImagerNotCovered(imager.norad_id, "no ephemeris table")
            found.extend(self._windows_for(track, site, unit, imager, start, end))
        return sorted(found, key=lambda window: window.rise)

    def _windows_for(
        self, track: LagrangeInterpolator, site: Site, unit: Unit, imager: Imager, start: dt.datetime, end: dt.datetime
    ) -> list[PassWindow]:
        table = track.table
        if start < table.start or end > table.stop:
            log.warning(
                "Ephemeris does not cover interval",
                norad_id=imager.norad_id,
                requested_start=start.isoformat(),
                requested_end=end.isoformat(),
                table_start=table.start.isoformat(),
                table_stop=table.stop.isoformat(),
            )
        start_s, end_s = track.seconds(start), track.seconds(end)
        lo_s, hi_s = max(start_s - SEARCH_MARGIN_S, 0.0), min(end_s + SEARCH_MARGIN_S, track.stop_s)
        if lo_s >= hi_s:
            return []
        windows = []
        for found in _PassSearch(track, site, imager.max_off_nadir_deg).passes(lo_s, hi_s):
            if not found.overlaps(start_s, end_s):
                continue
            if not found.complete:
                log.warning(
                    "Pass extends beyond searched ephemeris",
                    norad_id=imager.norad_id,
                    culmination=track.when(found.culmination_s).isoformat(),
                )
                continue
            windows.append(self._window(track, unit, imager, found))
        return windows

    def _window(self, track: LagrangeInterpolator, unit: Unit, imager: Imager, found: _Pass) -> PassWindow:
        culmination = track.when(found.culmination_s)
        return PassWindow(
            norad_id=imager.norad_id,
            name=track.table.name,
            sensor=imager.sensor,
            rise=track.when(found.rise_s),
            culmination=culmination,
            set=track.when(found.set_s),
            max_elevation_deg=found.max_elevation_deg,
            mask_elevation_deg=found.mask_elevation_deg,
            element_age_days=(culmination - track.table.created).total_seconds() / 86400.0,
            sunlit=self._sunlit(imager, unit, culmination),
            provider=self.name,
        )

    def _sunlit(self, imager: Imager, unit: Unit, culmination: dt.datetime) -> bool | None:
        if imager.sensor != "EO":
            return None
        return sun_elevation_deg(culmination, unit.lat_deg, unit.lon_deg) >= self.min_sun_elevation_deg
