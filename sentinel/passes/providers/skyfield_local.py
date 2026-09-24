"""Local pass prediction: SGP4 from public element sets, through Skyfield.

Runs entirely at the edge. It uses the bundled timescale only, so it never
loads a JPL ephemeris or touches the network, and the unit's position never
leaves the node.

A pass is the time the imager spends above the unit's *mask* elevation.
The mask is the lowest elevation at which the imager's field of regard
(`Imager.max_off_nadir_deg`, a planning assumption) reaches the unit, at
the element set's mean altitude.

The search runs one orbital period either side of [start, end]. A pass is
shorter than an orbit in low Earth orbit, so every pass that overlaps the
interval is found whole: true rise, culmination and set, even when those
fall outside it (the model.PassProvider convention). An element set beyond
low Earth orbit is refused rather than risk a clipped or missing pass.
Rise and set are refined so each window contains the true pass
(skyfield_passes).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence

from skyfield.api import EarthSatellite, load, wgs84
from skyfield.timelib import Timescale

from sentinel.obs import get_logger

from ..elements import (
    SECONDS_PER_DAY,
    ElementSet,
    ElementSetError,
    epoch_utc,
    mean_altitude_km,
    orbital_period_s,
    skip_reason,
)
from ..geometry import min_elevation_deg, sun_elevation_deg
from ..interval import require_interval
from ..model import Imager, PassWindow, Unit
from .skyfield_passes import Pass, find_passes

log = get_logger(__name__)

# Planning assumption: an optical imager needs the sun at least 10 deg above
# the unit's horizon at culmination to collect a usable image.
EO_MIN_SUN_ELEVATION_DEG = 10.0

# The conventional upper bound on a low-Earth-orbit period.
MAX_LEO_PERIOD_S = 128 * 60.0


class SkyfieldProvider:
    """PassProvider backed by Skyfield's SGP4 and event finder."""

    name = "skyfield-local"

    def __init__(self, element_sets: Mapping[int, ElementSet], timescale: Timescale | None = None):
        self._element_sets = element_sets
        self._ts = timescale or load.timescale(builtin=True)
        self._satellites: dict[int, EarthSatellite] = {}

    def windows(
        self, unit: Unit, imagers: Sequence[Imager], start: dt.datetime, end: dt.datetime
    ) -> list[PassWindow]:
        require_interval(start, end)
        found = [w for imager in imagers for w in self._imager_windows(unit, imager, start, end)]
        return sorted(found, key=lambda w: w.rise)

    def _imager_windows(self, unit: Unit, imager: Imager, start: dt.datetime, end: dt.datetime) -> list[PassWindow]:
        element_set = self._element_set(imager)
        mask_deg = min_elevation_deg(imager.max_off_nadir_deg, mean_altitude_km(element_set))
        margin = dt.timedelta(seconds=orbital_period_s(element_set))
        passes = find_passes(
            self._satellite(imager.norad_id, element_set),
            wgs84.latlon(unit.lat_deg, unit.lon_deg, elevation_m=unit.alt_m),
            self._ts.from_datetime(start - margin),
            self._ts.from_datetime(end + margin),
            mask_deg,
        )
        epoch = epoch_utc(element_set)
        windows = [
            _window(unit, imager, element_set["OBJECT_NAME"], found, mask_deg, epoch, self.name)
            for found in passes
            if found.rise <= end and found.set >= start
        ]
        _warn_if_stale(imager, epoch, windows)
        return windows

    def _element_set(self, imager: Imager) -> ElementSet:
        reason = skip_reason(imager, self._element_sets)
        if reason is not None:
            raise ElementSetError(
                f"imager {imager.norad_id} {imager.name!r}: {reason.value}; pair the catalog with match_catalog first"
            )
        element_set = self._element_sets[imager.norad_id]
        if orbital_period_s(element_set) > MAX_LEO_PERIOD_S:
            raise ElementSetError(f"imager {imager.norad_id} {imager.name!r}: not in low Earth orbit")
        return element_set

    def _satellite(self, norad_id: int, element_set: ElementSet) -> EarthSatellite:
        if norad_id not in self._satellites:
            self._satellites[norad_id] = EarthSatellite.from_omm(self._ts, element_set)
        return self._satellites[norad_id]


def _window(
    unit: Unit, imager: Imager, object_name: str, found: Pass, mask_deg: float, epoch: dt.datetime, provider: str
) -> PassWindow:
    return PassWindow(
        norad_id=imager.norad_id,
        name=object_name,
        sensor=imager.sensor,
        rise=found.rise,
        culmination=found.culmination,
        set=found.set,
        max_elevation_deg=found.max_elevation_deg,
        mask_elevation_deg=mask_deg,
        element_age_days=(found.culmination - epoch).total_seconds() / SECONDS_PER_DAY,
        sunlit=_sunlit(imager.sensor, found.culmination, unit),
        provider=provider,
    )


def _sunlit(sensor: str, culmination: dt.datetime, unit: Unit) -> bool | None:
    if sensor != "EO":
        return None
    return sun_elevation_deg(culmination, unit.lat_deg, unit.lon_deg) >= EO_MIN_SUN_ELEVATION_DEG


def _warn_if_stale(imager: Imager, epoch: dt.datetime, windows: list[PassWindow]) -> None:
    stale = [w for w in windows if w.stale]
    if stale:
        log.warning(
            "Stale element set",
            norad_id=imager.norad_id,
            epoch=epoch.isoformat(),
            max_age_days=round(max(w.element_age_days for w in stale), 2),
            stale_windows=len(stale),
        )
