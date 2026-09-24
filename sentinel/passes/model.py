"""The pass module's shared contract: units, imagers, windows, providers.

Every pass provider - local SGP4 from element sets, tabulated ephemeris,
or an external service - returns the same PassWindow, so the console, the
gap finder and the conformance suite never know which one ran (MOSA).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Sequence
from typing import Protocol

from .geometry import STALE_AFTER_DAYS, element_pad_s


@dataclasses.dataclass(frozen=True)
class Unit:
    unit_id: str
    lat_deg: float
    lon_deg: float
    alt_m: float = 0.0
    reaction_time_min: float = 30.0


@dataclasses.dataclass(frozen=True)
class Imager:
    norad_id: int
    name: str                    # expected OBJECT_NAME prefix in the element set
    sensor: str                  # "EO" | "SAR"
    max_off_nadir_deg: float     # field of regard: a planning assumption
    gsd_m: float | None = None
    basis: str = ""              # where the assumption comes from


@dataclasses.dataclass(frozen=True)
class PassWindow:
    norad_id: int
    name: str
    sensor: str
    rise: dt.datetime
    culmination: dt.datetime
    set: dt.datetime
    max_elevation_deg: float
    mask_elevation_deg: float    # the elevation the field of regard implies
    element_age_days: float
    sunlit: bool | None          # EO: unit lit at culmination; SAR: None
    provider: str

    @property
    def pad_s(self) -> float:
        return element_pad_s(self.element_age_days)

    @property
    def padded(self) -> tuple[dt.datetime, dt.datetime]:
        pad = dt.timedelta(seconds=self.pad_s)
        return self.rise - pad, self.set + pad

    @property
    def stale(self) -> bool:
        return self.element_age_days > STALE_AFTER_DAYS

    @property
    def usable(self) -> bool:
        """Can the sensor image the unit on this pass? EO needs daylight."""
        return self.sensor != "EO" or bool(self.sunlit)


class PassProvider(Protocol):
    """Convention every provider follows: return each pass that overlaps
    [start, end], with its true rise, culmination and set - even when they
    fall outside the interval - sorted by rise. Callers clip."""

    name: str

    def windows(
        self, unit: Unit, imagers: Sequence[Imager], start: dt.datetime, end: dt.datetime
    ) -> list[PassWindow]: ...
