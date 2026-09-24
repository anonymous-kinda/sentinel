"""RTN to ECI frame conversion.

A CDM carries each object's position covariance in that object's *own*
RTN frame (radial / along-track / cross-track). The two objects' RTN frames
are different frames - each is defined by that object's own position and
velocity - so the covariances cannot be added until both are expressed in a
common inertial frame.

Rotating only one object, or assuming the two share a frame, is the classic
error here. Tier 1 of the test ladder pins this down before any probability
is computed.
"""

from __future__ import annotations

import numpy as np


def rtn_to_eci_matrix(position: np.ndarray, velocity: np.ndarray) -> np.ndarray:
    """Return the 3x3 rotation whose columns are [R_hat, T_hat, C_hat] in ECI.

    R_hat  radial, along the position vector
    C_hat  cross-track, along the orbital angular momentum
    T_hat  along-track, completing the right-handed set

    The result is orthonormal with determinant +1, so `M @ C_rtn @ M.T`
    is a similarity transform and preserves trace and determinant.
    """
    r = np.asarray(position, dtype=float)
    v = np.asarray(velocity, dtype=float)

    r_norm = np.linalg.norm(r)
    if r_norm == 0.0:
        raise ValueError("position vector is zero; RTN frame is undefined")

    h = np.cross(r, v)
    h_norm = np.linalg.norm(h)
    if h_norm == 0.0:
        raise ValueError(
            "position and velocity are parallel; orbital plane is undefined"
        )

    r_hat = r / r_norm
    c_hat = h / h_norm
    t_hat = np.cross(c_hat, r_hat)

    return np.column_stack([r_hat, t_hat, c_hat])


def rotate_covariance_rtn_to_eci(
    covariance_rtn: np.ndarray, position: np.ndarray, velocity: np.ndarray
) -> np.ndarray:
    """Express an RTN-frame position covariance in ECI."""
    m = rtn_to_eci_matrix(position, velocity)
    cov = np.asarray(covariance_rtn, dtype=float)
    rotated: np.ndarray = m @ cov @ m.T
    return rotated
