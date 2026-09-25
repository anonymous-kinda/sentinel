"""Orbit arcs around TCA for the globe. Visualization only.

Two-body propagation from the CDM states, rotated from EME2000 to an
Earth-fixed frame by Greenwich mean sidereal time alone (no precession,
nutation or polar motion, UTC standing in for UT1). That is kilometre-class
accurate over a ±20 minute arc - fine for drawing where two objects meet,
and never used for any number the engine reports.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
from scipy.integrate import solve_ivp

from ..risk.types import Conjunction

MU_EARTH_M3_S2 = 3.986004418e14
# Arcs are drawn only from a state between the Earth's surface (WGS-84 polar
# radius) and its Hill sphere (about 1.5 million km). Outside that band a
# two-body Earth arc means nothing, and near r = 0 or at the float limit the
# integrator can take minutes to give up.
DRAWABLE_RADIUS_M = (6_356_752.3, 1.5e9)
_J2000 = dt.datetime(2000, 1, 1, 12, 0, 0, tzinfo=dt.UTC)


class TrajectoryUnavailable(ValueError):
    """The two-body arcs cannot be drawn for these states."""


def gmst_rad(when: dt.datetime) -> float:
    """IAU 1982 GMST, UTC used in place of UT1."""
    days = (when - _J2000).total_seconds() / 86400.0
    t = days / 36525.0
    deg = 280.46061837 + 360.98564736629 * days + 0.000387933 * t * t - t**3 / 38710000.0
    return math.radians(deg % 360.0)


def _eci_to_ecef(r_m: np.ndarray, when: dt.datetime) -> np.ndarray:
    theta = gmst_rad(when)
    c, s = math.cos(theta), math.sin(theta)
    rot = np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])
    return rot @ r_m


def _two_body(_t, y):
    r = y[:3]
    a = -MU_EARTH_M3_S2 * r / np.linalg.norm(r) ** 3
    return np.concatenate([y[3:], a])


def propagate_eci_m(r_km, v_km_s, offsets_s: np.ndarray) -> np.ndarray:
    """Positions (m, ECI) at each offset from the epoch, both directions."""
    y0 = np.concatenate([np.asarray(r_km, float) * 1000.0, np.asarray(v_km_s, float) * 1000.0])
    low, high = DRAWABLE_RADIUS_M
    if not low <= float(np.linalg.norm(y0[:3])) <= high:
        raise TrajectoryUnavailable("the state is not between the Earth's surface and its Hill sphere")
    out = np.empty((len(offsets_s), 3))
    fwd = offsets_s >= 0
    for mask, span in ((fwd, (0.0, float(offsets_s.max()))), (~fwd, (0.0, float(offsets_s.min())))):
        if not mask.any():
            continue
        if span[1] == 0.0:
            out[mask] = y0[:3]
            continue
        idx = np.flatnonzero(mask)
        # solve_ivp wants t_eval monotone in the direction of integration.
        idx = idx[np.argsort(offsets_s[idx])]
        if span[1] < 0:
            idx = idx[::-1]
        sol = solve_ivp(
            _two_body, span, y0, t_eval=offsets_s[idx], rtol=1e-10, atol=1e-6, method="DOP853"
        )
        if not sol.success:
            # e.g. an arc through the Earth's centre, where two-body gravity is singular
            raise TrajectoryUnavailable(f"two-body propagation failed: {sol.message}")
        out[idx] = sol.y[:3].T
    return out


def encounter_arcs_ecef(
    conjunction: Conjunction, tca: dt.datetime, half_window_s: float = 1200.0, step_s: float = 30.0
) -> dict:
    offsets = np.arange(-half_window_s, half_window_s + step_s / 2, step_s)
    try:
        times = [tca + dt.timedelta(seconds=float(off)) for off in offsets]
    except OverflowError as exc:
        raise TrajectoryUnavailable("the arc runs past the last representable date") from exc
    arcs = {}
    for name, state in (("primary", conjunction.primary), ("secondary", conjunction.secondary)):
        eci = propagate_eci_m(state.position_km, state.velocity_km_s, offsets)
        samples = []
        for off, when, r in zip(offsets, times, eci):
            x, y, z = _eci_to_ecef(r, when)
            samples.append([float(off), float(x), float(y), float(z)])
        arcs[name] = samples
    return arcs
