"""A public element set as an orbit: SGP4 through Skyfield.

Two frames matter here. SGP4 produces TEME (true equator, mean equinox of
date). A CDM needs an inertial frame the engine accepts, and GCRF is the
one Skyfield converts to natively (its GCRS), with no Earth-orientation
data - so no network - required.

The search stays in TEME. Range and range rate do not depend on the
frame: at any instant both objects are rotated by the same matrix, which
preserves distances. Only the states written into a CDM are converted.
"""

from __future__ import annotations

import datetime as dt
import functools

import numpy as np
from skyfield.api import EarthSatellite, Timescale, load
from skyfield.sgp4lib import SGP4_ERRORS

from ..passes.element_store import element_epoch

DAY_S = 86400.0
_UNIX_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
_UNIX_EPOCH_JD = 2440587.5


class OrbitUnusable(ValueError):
    """This element set cannot give a trustworthy position. `code` names why."""

    def __init__(self, code: str, detail: str, norad_id: int | None = None):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.norad_id = norad_id


@functools.cache
def _timescale() -> Timescale:
    """Skyfield's bundled leap-second and Delta T tables; never downloads."""
    return load.timescale(builtin=True)


def _utc_jd(when: dt.datetime) -> tuple[float, float]:
    """UTC Julian date as (whole, fraction of day): SGP4's time argument."""
    if when.tzinfo is None:
        raise ValueError("refusing a naive datetime; screening times are UTC")
    since = when.astimezone(dt.UTC) - _UNIX_EPOCH
    return _UNIX_EPOCH_JD + since.days, (since.seconds + since.microseconds / 1e6) / DAY_S


def _sgp4_error(code: int) -> str:
    return f"SGP4 error {code}: {SGP4_ERRORS.get(code, 'unknown')}"


class Orbit:
    """One object's element set, propagated by SGP4."""

    def __init__(self, fields: dict, satellite: EarthSatellite):
        self.fields = fields
        self._satellite = satellite

    @classmethod
    def from_omm(cls, fields: dict) -> Orbit:
        norad_id = fields.get("NORAD_CAT_ID")
        try:
            satellite = EarthSatellite.from_omm(_timescale(), fields)
        except (KeyError, TypeError, ValueError) as exc:
            raise OrbitUnusable("UNUSABLE_ELEMENTS", f"{type(exc).__name__}: {exc}", norad_id) from exc
        if satellite.model.error:
            raise OrbitUnusable("UNUSABLE_ELEMENTS", _sgp4_error(satellite.model.error), norad_id)
        return cls(fields, satellite)

    @property
    def norad_id(self) -> int:
        return int(self.fields["NORAD_CAT_ID"])

    @property
    def name(self) -> str:
        return str(self.fields.get("OBJECT_NAME") or self.norad_id)

    @property
    def epoch(self) -> dt.datetime:
        return element_epoch(self.fields)

    @property
    def radial_band_km(self) -> tuple[float, float]:
        """(perigee, apogee) radius of the mean elements, km from the Earth's centre."""
        model = self._satellite.model
        return (1.0 + model.altp) * model.radiusearthkm, (1.0 + model.alta) * model.radiusearthkm

    def teme_km(self, start: dt.datetime, offsets_s: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """TEME position (km) and velocity (km/s) at start + each offset, shape [n, 3]."""
        jd, fraction = _utc_jd(start)
        offsets = np.asarray(offsets_s, dtype=float)
        errors, position, velocity = self._satellite.model.sgp4_array(
            np.full_like(offsets, jd), fraction + offsets / DAY_S
        )
        failed = np.flatnonzero(errors)
        if failed.size:
            raise OrbitUnusable("PROPAGATION_FAILED", _sgp4_error(int(errors[failed[0]])), self.norad_id)
        return position, velocity

    def gcrf_state_km(self, when: dt.datetime) -> tuple[np.ndarray, np.ndarray]:
        """GCRF position (km) and velocity (km/s) at one instant, via Skyfield's GCRS."""
        self.teme_km(when, np.zeros(1))  # the same SGP4 error check as the search
        geocentric = self._satellite.at(_timescale().from_datetime(when))
        return geocentric.position.km, geocentric.velocity.km_per_s
