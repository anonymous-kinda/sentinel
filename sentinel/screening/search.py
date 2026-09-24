"""Find every local minimum of range below a threshold, given relative motion.

The search knows nothing about orbits. It takes a function from time
(seconds from the window start) to relative position and velocity, so it
can be tested against motion whose answer is exact, and so a different
propagator can drive it unchanged.

Three steps:

1. **Coarse sampling.** Relative state at a fixed step across the window.
2. **Bracketing.** A range minimum lies between two samples wherever the
   range rate (dr . dv) goes from closing (<= 0) to opening (> 0). A bracket
   is kept only if the range *could* dip below the threshold inside it:
   with |d|r|/dt| <= V, the range anywhere in a step of length h is at least
   (r_a + r_b - V h) / 2. V bounds the relative speed over the step: the
   larger sampled speed plus the most two orbiting objects can accelerate
   apart in one step. The bound is conservative, so no approach is dropped
   here however fast the pass.
3. **Refinement.** Brent's method on the range rate, inside the bracket,
   to a microsecond. The root is the time of closest approach (TCA).

The one assumption is at most one range minimum per step. Crossing orbits
meet about twice a revolution, tens of minutes apart, so a 60 s step holds
it with a wide margin; tests/screening/test_screen.py checks the whole
snapshot against 1 s brute-force sampling.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable

import numpy as np
from scipy.optimize import brentq

RelativeState = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]
"""Seconds from the window start -> (dr_km [n, 3], dv_km_s [n, 3])."""

DEFAULT_STEP_S = 60.0
TCA_TOLERANCE_S = 1e-6
# Two objects anywhere above the Earth's surface each accelerate at under
# 9.81e-3 km/s^2, so their relative acceleration is under twice that.
MAX_RELATIVE_ACCELERATION_KM_S2 = 0.02


@dataclasses.dataclass(frozen=True)
class RangeMinimum:
    t_s: float
    miss_distance_km: float
    relative_speed_km_s: float


def find_close_approaches(
    relative_state: RelativeState,
    duration_s: float,
    threshold_km: float,
    step_s: float = DEFAULT_STEP_S,
) -> list[RangeMinimum]:
    """Every range minimum within the window at or below threshold_km, in time order."""
    require_positive(duration_s=duration_s, threshold_km=threshold_km, step_s=step_s)
    t_s = sample_times(duration_s, step_s)
    dr, dv = relative_state(t_s)
    found = [_refine(relative_state, a, b) for a, b in _brackets(t_s, dr, dv, threshold_km)]
    return [m for m in found if m.miss_distance_km <= threshold_km]


def sample_times(duration_s: float, step_s: float) -> np.ndarray:
    """The coarse grid: both window ends included, no step longer than step_s."""
    return np.linspace(0.0, duration_s, math.ceil(duration_s / step_s) + 1)


def require_positive(**values: float) -> None:
    """Raise ValueError naming the first value that is not a positive finite number."""
    for name, value in values.items():
        if not (math.isfinite(value) and value > 0.0):
            raise ValueError(f"{name} must be a positive finite number, got {value!r}")


def _brackets(t_s: np.ndarray, dr: np.ndarray, dv: np.ndarray, threshold_km: float) -> list[tuple[float, float]]:
    range_km = np.linalg.norm(dr, axis=1)
    speed_km_s = np.linalg.norm(dv, axis=1)
    range_rate = np.einsum("ij,ij->i", dr, dv)
    step_s = np.diff(t_s)
    minimum_inside = (range_rate[:-1] <= 0.0) & (range_rate[1:] > 0.0)
    speed_bound = np.maximum(speed_km_s[:-1], speed_km_s[1:]) + MAX_RELATIVE_ACCELERATION_KM_S2 * step_s
    lowest_possible_km = (range_km[:-1] + range_km[1:] - speed_bound * step_s) / 2.0
    keep = np.flatnonzero(minimum_inside & (lowest_possible_km <= threshold_km))
    return [(float(t_s[i]), float(t_s[i + 1])) for i in keep]


def _state_at(relative_state: RelativeState, t_s: float) -> tuple[np.ndarray, np.ndarray]:
    dr, dv = relative_state(np.array([t_s]))
    return dr[0], dv[0]


def _refine(relative_state: RelativeState, a_s: float, b_s: float) -> RangeMinimum:
    def range_rate(t_s: float) -> float:
        dr, dv = _state_at(relative_state, t_s)
        return float(dr @ dv)

    tca_s = brentq(range_rate, a_s, b_s, xtol=TCA_TOLERANCE_S)
    dr, dv = _state_at(relative_state, tca_s)
    return RangeMinimum(tca_s, float(np.linalg.norm(dr)), float(np.linalg.norm(dv)))
