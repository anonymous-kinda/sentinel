"""Encounter-plane construction.

Under the linear relative-motion model the two objects move in straight
lines through the brief window around closest approach. The collision
integral then collapses onto the plane normal to the relative velocity - the
encounter plane - which is what makes the 2D method tractable.

Basis convention:

    z_hat  = dv / |dv|                    normal to the plane
    x_hat  = normalised component of dr perpendicular to dv
    y_hat  = z_hat x x_hat                completes a right-handed set

At a true time of closest approach `dr . z_hat` is zero by definition, so
x_hat is simply the miss direction and the projected miss vector is
(|dr|, 0). The engine computes the residual rather than assuming it, because
a non-zero residual means the supplied TCA is not a closest approach.
"""

from __future__ import annotations

import numpy as np

_DEGENERATE_MISS_M = 1e-12


def _any_unit_perpendicular_to(axis: np.ndarray) -> np.ndarray:
    """Pick an arbitrary unit vector perpendicular to `axis`.

    Used only in the degenerate direct-hit case, where the miss vector is
    zero and the in-plane orientation is genuinely arbitrary - any
    perpendicular basis gives the same probability.
    """
    seed = np.array([1.0, 0.0, 0.0])
    if abs(axis @ seed) > 0.9:
        seed = np.array([0.0, 1.0, 0.0])
    perp = seed - (seed @ axis) * axis
    unit: np.ndarray = perp / np.linalg.norm(perp)
    return unit


def encounter_plane_basis(
    relative_position: np.ndarray, relative_velocity: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (x_hat, y_hat, z_hat) for the encounter plane."""
    dr = np.asarray(relative_position, dtype=float)
    dv = np.asarray(relative_velocity, dtype=float)

    dv_norm = np.linalg.norm(dv)
    if dv_norm == 0.0:
        raise ValueError("relative velocity is zero; encounter plane is undefined")

    z_hat = dv / dv_norm
    r_perp = dr - (dr @ z_hat) * z_hat
    r_perp_norm = np.linalg.norm(r_perp)

    if r_perp_norm < _DEGENERATE_MISS_M:
        x_hat = _any_unit_perpendicular_to(z_hat)
    else:
        x_hat = r_perp / r_perp_norm

    y_hat = np.cross(z_hat, x_hat)
    return x_hat, y_hat, z_hat


def projection_matrix(
    relative_position: np.ndarray, relative_velocity: np.ndarray
) -> np.ndarray:
    """Return the 2x3 matrix projecting ECI vectors into the encounter plane."""
    x_hat, y_hat, _ = encounter_plane_basis(relative_position, relative_velocity)
    return np.vstack([x_hat, y_hat])


def tca_residual(
    relative_position: np.ndarray, relative_velocity: np.ndarray
) -> float:
    """Component of relative position along relative velocity, in input units.

    Zero at a true closest approach. A large value indicates the supplied
    state is not at TCA.
    """
    dr = np.asarray(relative_position, dtype=float)
    dv = np.asarray(relative_velocity, dtype=float)
    dv_norm = np.linalg.norm(dv)
    if dv_norm == 0.0:
        raise ValueError("relative velocity is zero; TCA residual is undefined")
    return float(dr @ (dv / dv_norm))
