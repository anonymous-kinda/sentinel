"""Lagrange interpolation of a StateTable's positions, over a sliding window.

Degree 8 (nine states around the query time) and a table step of at most
MAX_STEP_S. Measured on Earth-fixed LEO positions (WORLDVIEW-3, SENTINEL-1A
and LANDSAT 8, 6 h, every 5 s, against Skyfield SGP4):

    step     interior      outermost four intervals (window not centred)
    60 s     < 0.1 mm      < 0.1 mm
    180 s    7 mm          0.14 m
    300 s    0.57 m        12 m
    600 s    171 m         (not measured; refused)

12 m is 1.6 ms of along-track motion, far inside the 0.1 s pass-timing
tolerance, so 300 s is the limit; a coarser table is refused rather than
interpolated badly. tests/ephemeris/test_interpolate.py pins both bounds.

Positions only: velocities, where a source has them, are not used.
It never extrapolates. A time outside the table raises.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
from numpy.typing import ArrayLike

from .table import EphemerisRejected, StateTable

LAGRANGE_DEGREE = 8
MAX_STEP_S = 300.0
_POINTS = LAGRANGE_DEGREE + 1
_OFF_DIAGONAL = ~np.eye(_POINTS, dtype=bool)


def _weights(nodes_s: np.ndarray, times_s: np.ndarray) -> np.ndarray:
    """Lagrange basis weights, one row per query: w_j = prod_{k!=j} (t - t_k) / (t_j - t_k)."""
    to_query = times_s[:, None] - nodes_s                       # (M, P)
    between = nodes_s[:, :, None] - nodes_s[:, None, :]         # (M, P, P)
    numerator = np.prod(np.where(_OFF_DIAGONAL, to_query[:, None, :], 1.0), axis=2)
    denominator = np.prod(np.where(_OFF_DIAGONAL, between, 1.0), axis=2)
    return numerator / denominator


class LagrangeInterpolator:
    """Positions of one StateTable at any time inside it, in seconds from its start."""

    def __init__(self, table: StateTable):
        self.table = table
        self._times_s = np.array([(epoch - table.start).total_seconds() for epoch in table.epochs])
        self._require_interpolable()

    def _require_interpolable(self) -> None:
        if len(self._times_s) < _POINTS:
            raise EphemerisRejected(
                "TOO_FEW_STATES",
                f"{len(self._times_s)} states; degree-{LAGRANGE_DEGREE} interpolation needs {_POINTS}",
            )
        largest_step_s = float(np.diff(self._times_s).max())
        if largest_step_s > MAX_STEP_S:
            raise EphemerisRejected(
                "STEP_TOO_COARSE",
                f"a {largest_step_s:.0f} s gap between states; at most {MAX_STEP_S:.0f} s interpolates to < 1 m",
            )

    @property
    def stop_s(self) -> float:
        return float(self._times_s[-1])

    def seconds(self, when: dt.datetime) -> float:
        return (when - self.table.start).total_seconds()

    def when(self, seconds: float) -> dt.datetime:
        return self.table.start + dt.timedelta(seconds=seconds)

    def positions_km(self, times_s: ArrayLike) -> np.ndarray:
        """Positions (M, 3) at `times_s` seconds from the table start."""
        times = np.atleast_1d(np.asarray(times_s, dtype=float))
        if (times < 0.0).any() or (times > self.stop_s).any():
            raise ValueError("refusing to extrapolate beyond the state table")
        interval = np.searchsorted(self._times_s, times, side="right") - 1
        first = np.clip(interval - LAGRANGE_DEGREE // 2, 0, len(self._times_s) - _POINTS)
        window = first[:, None] + np.arange(_POINTS)
        weights = _weights(self._times_s[window], times)
        return np.einsum("mp,mpc->mc", weights, self.table.positions_km[window])
