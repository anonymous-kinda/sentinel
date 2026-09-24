"""Where the unit is on the WGS84 ellipsoid, and how high it sees a satellite.

A provider that works from Earth-fixed positions needs the unit's own
Earth-fixed position and its local vertical. Geodetic latitude on the
ellipsoid, not the spherical Earth of geometry.py: the difference is up to
21 km in position and 0.19 degrees in the vertical, which is not negligible
when a field of regard puts the mask at 80 degrees.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from .geometry import EARTH_RADIUS_KM
from .model import Unit

WGS84_FLATTENING = 1.0 / 298.257223563
_ECCENTRICITY_SQUARED = WGS84_FLATTENING * (2.0 - WGS84_FLATTENING)


@dataclasses.dataclass(frozen=True, eq=False)
class Site:
    ecef_km: np.ndarray   # Earth-fixed (ITRF) position
    up: np.ndarray        # unit vector along the geodetic vertical

    @classmethod
    def from_unit(cls, unit: Unit) -> Site:
        lat, lon = math.radians(unit.lat_deg), math.radians(unit.lon_deg)
        # EARTH_RADIUS_KM is the WGS84 semi-major axis.
        normal_km = EARTH_RADIUS_KM / math.sqrt(1.0 - _ECCENTRICITY_SQUARED * math.sin(lat) ** 2)
        height_km = unit.alt_m / 1000.0
        up = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
        ecef_km = np.array([
            (normal_km + height_km) * up[0],
            (normal_km + height_km) * up[1],
            (normal_km * (1.0 - _ECCENTRICITY_SQUARED) + height_km) * up[2],
        ])
        return cls(ecef_km, up)

    def elevation_deg(self, positions_km: np.ndarray) -> np.ndarray:
        """Geometric elevation (no refraction) of Earth-fixed positions (M, 3).

        atan2 of the vertical and horizontal components, not arcsin of their
        ratio, which loses precision near the zenith."""
        line_of_sight = np.atleast_2d(positions_km) - self.ecef_km
        vertical_km = line_of_sight @ self.up
        horizontal_km = np.linalg.norm(line_of_sight - np.outer(vertical_km, self.up), axis=1)
        return np.degrees(np.arctan2(vertical_km, horizontal_km))
