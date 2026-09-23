"""Tier 2 - the 2D Gaussian integral over the hard-body disk.

Every expectation here is either a closed form or an independent numerical
oracle (scipy.integrate.dblquad). Nothing is a value copied from a previous
run of this code, which would only prove the code agrees with itself.

Rungs 7-11 of the ladder, plus an independent-oracle cross-check that gives
Tier 3 something to stand on before the CARA fixtures arrive.
"""

import numpy as np
import pytest
from scipy.integrate import dblquad

from sentinel.risk.integrate import gaussian_mass_over_disk

pytestmark = pytest.mark.tier2


def _dblquad_oracle(cov2d, mu, radius):
    """Independent 2D numerical integration of the same quantity.

    Deliberately implemented by a different route (scipy adaptive quadrature
    over Cartesian coordinates) than the engine's Gauss-Legendre quadrature
    in polar-substituted form, so agreement is meaningful.
    """
    inv = np.linalg.inv(cov2d)
    norm = 1.0 / (2.0 * np.pi * np.sqrt(np.linalg.det(cov2d)))

    def integrand(y, x):
        d = np.array([x - mu[0], y - mu[1]])
        return norm * np.exp(-0.5 * d @ inv @ d)

    value, _ = dblquad(
        integrand,
        -radius,
        radius,
        lambda x: -np.sqrt(max(radius**2 - x**2, 0.0)),
        lambda x: np.sqrt(max(radius**2 - x**2, 0.0)),
        epsabs=1e-14,
        epsrel=1e-12,
    )
    return value


# --- rung 7 ---------------------------------------------------------------
@pytest.mark.parametrize("sigma,radius", [(50.0, 5.0), (10.0, 10.0), (200.0, 1.0)])
def test_isotropic_zero_miss_matches_closed_form(sigma, radius):
    """For isotropic covariance centred on the disk, the mass integrates to
    the Rayleigh CDF: 1 - exp(-R^2 / 2 sigma^2)."""
    cov = np.eye(2) * sigma**2
    expected = 1.0 - np.exp(-(radius**2) / (2.0 * sigma**2))

    got = gaussian_mass_over_disk(cov, np.zeros(2), radius)

    assert np.isclose(got, expected, rtol=1e-10)


# --- rung 8 ---------------------------------------------------------------
def test_pc_decreases_monotonically_with_miss_distance():
    cov = np.eye(2) * 50.0**2
    values = [
        gaussian_mass_over_disk(cov, np.array([d, 0.0]), 10.0)
        for d in [0.0, 25.0, 50.0, 100.0, 200.0, 400.0]
    ]
    assert all(a > b for a, b in zip(values, values[1:]))


# --- rung 9 ---------------------------------------------------------------
def test_pc_increases_monotonically_with_hard_body_radius():
    cov = np.eye(2) * 50.0**2
    mu = np.array([100.0, 0.0])
    values = [gaussian_mass_over_disk(cov, mu, r) for r in [1.0, 5.0, 10.0, 25.0, 50.0]]
    assert all(a < b for a, b in zip(values, values[1:]))


# --- rung 10 --------------------------------------------------------------
def test_pc_approaches_one_when_disk_dwarfs_uncertainty():
    cov = np.eye(2) * 1.0**2
    got = gaussian_mass_over_disk(cov, np.zeros(2), 100.0)
    assert got > 1.0 - 1e-12
    assert got <= 1.0 + 1e-12


# --- rung 11 --------------------------------------------------------------
def test_pc_approaches_zero_as_disk_shrinks():
    cov = np.eye(2) * 50.0**2
    values = [gaussian_mass_over_disk(cov, np.zeros(2), r) for r in [1.0, 1e-2, 1e-4]]
    assert all(a > b for a, b in zip(values, values[1:]))
    assert values[-1] < 1e-10
    assert values[-1] >= 0.0


def test_probability_never_exceeds_unity_or_goes_negative():
    rng = np.random.default_rng(20260922)
    for _ in range(50):
        sx, sy = rng.uniform(1.0, 500.0, size=2)
        cov = np.diag([sx**2, sy**2])
        mu = rng.uniform(-300.0, 300.0, size=2)
        radius = rng.uniform(0.5, 100.0)
        p = gaussian_mass_over_disk(cov, mu, radius)
        assert 0.0 <= p <= 1.0


# --- independent oracle ---------------------------------------------------
@pytest.mark.parametrize(
    "sx,sy,mux,muy,radius",
    [
        (50.0, 50.0, 100.0, 0.0, 10.0),      # isotropic, offset
        (200.0, 20.0, 150.0, 0.0, 15.0),     # strongly anisotropic
        (30.0, 90.0, 40.0, 60.0, 8.0),       # anisotropic, offset in both axes
        (12.0, 12.0, 0.0, 0.0, 30.0),        # disk dwarfs uncertainty
        (500.0, 400.0, 20.0, -35.0, 5.0),    # tiny disk, broad uncertainty
    ],
)
def test_agrees_with_independent_numerical_oracle(sx, sy, mux, muy, radius):
    cov = np.diag([sx**2, sy**2])
    mu = np.array([mux, muy])

    got = gaussian_mass_over_disk(cov, mu, radius)
    expected = _dblquad_oracle(cov, mu, radius)

    assert np.isclose(got, expected, rtol=1e-8), f"{got} vs {expected}"


def test_agrees_with_oracle_for_rotated_covariance():
    """Off-diagonal covariance exercises the eigendecomposition path."""
    theta = np.deg2rad(37.0)
    rot = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    cov = rot @ np.diag([180.0**2, 25.0**2]) @ rot.T
    mu = np.array([120.0, -45.0])

    got = gaussian_mass_over_disk(cov, mu, 12.0)
    expected = _dblquad_oracle(cov, mu, 12.0)

    assert np.isclose(got, expected, rtol=1e-8), f"{got} vs {expected}"


def test_result_is_invariant_under_rotation_of_the_whole_problem():
    """Rotating covariance and miss vector together must not change Pc."""
    cov = np.diag([180.0**2, 25.0**2])
    mu = np.array([120.0, 0.0])
    base = gaussian_mass_over_disk(cov, mu, 12.0)

    for deg in (13.0, 45.0, 90.0, 211.0):
        t = np.deg2rad(deg)
        rot = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
        got = gaussian_mass_over_disk(rot @ cov @ rot.T, rot @ mu, 12.0)
        assert np.isclose(got, base, rtol=1e-10), f"{deg} deg: {got} vs {base}"
