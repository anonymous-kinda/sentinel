"""Tier 1 - geometry only. No probability is computed anywhere in this file.

Rungs 1-6 of the ladder in docs/risk-engine-design.md section 7.
"""

import numpy as np
import pytest

from sentinel.risk.frames import rtn_to_eci_matrix, rotate_covariance_rtn_to_eci
from sentinel.risk.geometry import encounter_plane_basis, projection_matrix
from sentinel.risk.types import Method, RefusalReason
from sentinel.risk.engine import assess

from .conftest import make_conjunction

pytestmark = pytest.mark.tier1


# --- rung 1 ---------------------------------------------------------------
def test_rtn_to_eci_matrix_is_orthonormal_with_unit_determinant():
    r = np.array([6800.0, 1200.0, -400.0])
    v = np.array([-1.3, 6.9, 2.2])

    m = rtn_to_eci_matrix(r, v)

    np.testing.assert_allclose(m.T @ m, np.eye(3), atol=1e-12)
    assert np.isclose(np.linalg.det(m), 1.0, atol=1e-12)


# --- rung 2 ---------------------------------------------------------------
def test_known_state_produces_known_rtn_basis():
    """Circular equatorial, prograde: RTN axes coincide with ECI axes."""
    r = np.array([7000.0, 0.0, 0.0])
    v = np.array([0.0, 7.5, 0.0])

    m = rtn_to_eci_matrix(r, v)

    # Columns are [R_hat, T_hat, C_hat] expressed in ECI.
    np.testing.assert_allclose(m[:, 0], [1.0, 0.0, 0.0], atol=1e-12)  # radial
    np.testing.assert_allclose(m[:, 1], [0.0, 1.0, 0.0], atol=1e-12)  # along-track
    np.testing.assert_allclose(m[:, 2], [0.0, 0.0, 1.0], atol=1e-12)  # cross-track


def test_retrograde_state_flips_cross_track_and_along_track():
    """The secondary in the test builder: cross-track is -z, along-track -y."""
    r = np.array([7000.0, 0.0, 0.0])
    v = np.array([0.0, -7.5, 0.0])

    m = rtn_to_eci_matrix(r, v)

    np.testing.assert_allclose(m[:, 0], [1.0, 0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(m[:, 1], [0.0, -1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(m[:, 2], [0.0, 0.0, -1.0], atol=1e-12)


# --- rung 3 ---------------------------------------------------------------
def test_covariance_round_trips_through_rotation():
    r = np.array([6800.0, 1200.0, -400.0])
    v = np.array([-1.3, 6.9, 2.2])
    cov_rtn = np.diag([100.0, 2500.0, 40.0])

    m = rtn_to_eci_matrix(r, v)
    cov_eci = rotate_covariance_rtn_to_eci(cov_rtn, r, v)
    recovered = m.T @ cov_eci @ m

    np.testing.assert_allclose(recovered, cov_rtn, atol=1e-9)


def test_rotation_preserves_trace_and_determinant():
    """A similarity transform by an orthonormal matrix is invariant in both."""
    r = np.array([6800.0, 1200.0, -400.0])
    v = np.array([-1.3, 6.9, 2.2])
    cov_rtn = np.diag([100.0, 2500.0, 40.0])

    cov_eci = rotate_covariance_rtn_to_eci(cov_rtn, r, v)

    assert np.isclose(np.trace(cov_eci), np.trace(cov_rtn), rtol=1e-12)
    assert np.isclose(np.linalg.det(cov_eci), np.linalg.det(cov_rtn), rtol=1e-12)


# --- rung 4 ---------------------------------------------------------------
def test_encounter_plane_basis_is_orthonormal_and_normal_to_relative_velocity():
    dr = np.array([120.0, 0.0, 0.0])
    dv = np.array([0.0, -15000.0, 0.0])

    x_hat, y_hat, z_hat = encounter_plane_basis(dr, dv)

    for a in (x_hat, y_hat, z_hat):
        assert np.isclose(np.linalg.norm(a), 1.0, atol=1e-12)
    assert np.isclose(x_hat @ y_hat, 0.0, atol=1e-12)
    assert np.isclose(x_hat @ z_hat, 0.0, atol=1e-12)
    assert np.isclose(y_hat @ z_hat, 0.0, atol=1e-12)

    # z_hat is parallel to dv
    np.testing.assert_allclose(z_hat, dv / np.linalg.norm(dv), atol=1e-12)


def test_encounter_plane_basis_matches_hand_computed_geometry():
    """The builder's geometry, worked by hand in conftest's docstring."""
    dr = np.array([100.0, 0.0, 0.0])
    dv = np.array([0.0, -15000.0, 0.0])

    x_hat, y_hat, z_hat = encounter_plane_basis(dr, dv)

    np.testing.assert_allclose(x_hat, [1.0, 0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(y_hat, [0.0, 0.0, 1.0], atol=1e-12)
    np.testing.assert_allclose(z_hat, [0.0, -1.0, 0.0], atol=1e-12)


# --- rung 5 ---------------------------------------------------------------
def test_projected_miss_vector_has_zero_second_component():
    dr = np.array([137.0, 0.0, 0.0])
    dv = np.array([0.0, -15000.0, 0.0])

    p = projection_matrix(dr, dv)
    mu = p @ dr

    assert np.isclose(mu[0], 137.0, atol=1e-9)
    assert np.isclose(mu[1], 0.0, atol=1e-9)


def test_projected_miss_second_component_zero_for_oblique_geometry():
    """Holds for any geometry, not just the axis-aligned builder."""
    dr = np.array([90.0, 30.0, -40.0])
    dv = np.array([-4000.0, 11000.0, 2000.0])
    dr = dr - (dr @ dv) / (dv @ dv) * dv  # force a true TCA

    p = projection_matrix(dr, dv)
    mu = p @ dr

    assert np.isclose(mu[1], 0.0, atol=1e-9)
    assert np.isclose(mu[0], np.linalg.norm(dr), rtol=1e-12)


# --- rung 6 ---------------------------------------------------------------
def test_tca_inconsistent_input_is_refused_not_processed():
    """A relative position with a large component along relative velocity is
    not a closest approach. Refuse rather than silently assess it."""
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)

    # Displace the secondary along the relative-velocity axis (ECI y).
    bad_secondary = conj.secondary.replace(
        position_km=conj.secondary.position_km + np.array([0.0, 5.0, 0.0])
    )
    bad = conj.replace(secondary=bad_secondary)

    result = assess(bad)

    assert result.method is Method.REFUSED
    assert result.refusal_reason is RefusalReason.TCA_INCONSISTENT
    assert result.pc is None
