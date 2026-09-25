"""Tier 2 - the 2D Gaussian integral over the hard-body disk.

Every expectation here is either a closed form or an independent numerical
oracle (scipy.integrate.dblquad). Nothing is a value copied from a previous
run of this code, which would only prove the code agrees with itself.

Rungs 7-11 of the ladder, plus an independent-oracle cross-check that gives
Tier 3 something to stand on before the CARA fixtures arrive.
"""

import math

import numpy as np
import pytest
from scipy.integrate import dblquad
from scipy.special import ndtr

from sentinel.risk import integrate
from sentinel.risk.integrate import gaussian_mass_over_disk

pytestmark = pytest.mark.tier2


def _dblquad_oracle(cov2d, mu, radius, window_sigmas=None):
    """Independent 2D numerical integration of the same quantity.

    Deliberately implemented by a different route (scipy adaptive quadrature
    over Cartesian coordinates) than the engine's Gauss-Legendre quadrature
    in polar-substituted form, so agreement is meaningful.

    `window_sigmas` limits x to that many of the widest sigma around the
    mean. An adaptive rule started across the whole disk can step over a
    peak much narrower than the disk; beyond 40 sigma the Gaussian is below
    exp(-800), which float64 cannot represent, so the limit changes nothing.
    """
    inv = np.linalg.inv(cov2d)
    norm = 1.0 / (2.0 * np.pi * np.sqrt(np.linalg.det(cov2d)))

    def integrand(y, x):
        d = np.array([x - mu[0], y - mu[1]])
        return norm * np.exp(-0.5 * d @ inv @ d)

    lo, hi = -radius, radius
    if window_sigmas is not None:
        reach = window_sigmas * math.sqrt(np.max(np.linalg.eigvalsh(cov2d)))
        lo, hi = max(lo, mu[0] - reach), min(hi, mu[0] + reach)

    value, _ = dblquad(
        integrand,
        lo,
        hi,
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


# --- the disk dwarfs the uncertainty ---------------------------------------
# When R / sigma_min is large the integrand is a spike far narrower than any
# fixed grid over the disk. The expectations below are limits as sigma / R
# goes to zero, derived by hand; none is a value this code produced.


def _rotation(deg):
    t = np.deg2rad(deg)
    return np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])


def test_a_tiny_covariance_inside_the_disk_carries_all_of_its_mass():
    """sigma ~1e-4 m, mean 10.4 m from the centre of a 20 m disk. The nearest
    edge is 9.56 m, about 68,000 sigma, away, so the mass outside is below
    exp(-2e9) and the answer is 1 to double precision. The 4096-panel grid
    returned 0.013."""
    got = gaussian_mass_over_disk(np.diag([1e-8, 2e-8]), np.array([10.0, 3.0]), 20.0)
    assert got == pytest.approx(1.0, abs=1e-12)


def test_a_tiny_covariance_outside_the_disk_carries_none_of_its_mass():
    """Mean 5.18 m, about 36,000 sigma, outside the edge: the mass is below
    exp(-6e8), which float64 cannot represent."""
    got = gaussian_mass_over_disk(np.diag([1e-8, 2e-8]), np.array([25.0, 3.0]), 20.0)
    assert 0.0 <= got < 1e-300


@pytest.mark.parametrize("sigma_over_radius", [1e-5, 1e-6])
@pytest.mark.parametrize(
    "shape",
    [np.eye(2), np.diag([1.0, 4.0]), _rotation(30.0) @ np.diag([1.0, 9.0]) @ _rotation(30.0).T],
    ids=["isotropic", "axis-aligned", "rotated"],
)
@pytest.mark.parametrize("alpha_deg", [0.0, 40.0, 90.0, 225.0])
def test_a_mean_on_the_edge_sees_half_the_mass_less_the_curvature(sigma_over_radius, shape, alpha_deg):
    """The boundary limit. With the mean on the circle, outward normal n,
    write N and T for the offsets along n and along the tangent. Inside the
    disk is N <= -T^2 / 2R + O(T^4 / R^3). Expanding Phi to first order in
    1/R (the second-order term is odd in T and vanishes):

        Pc = 1/2 - det(C) / (2 sigma_n^3 R sqrt(2 pi)) + O((sigma / R)^3)

    with sigma_n^2 = n' C n; det(C) / sigma_n^2 is the variance of T given
    N. At sigma / R = 1e-5 the curvature term is ~1e-6 and the remainder
    ~1e-15, so the tolerance tests the curvature term to 0.1 percent."""
    radius = 20.0
    cov = shape * (sigma_over_radius * radius) ** 2
    alpha = np.deg2rad(alpha_deg)
    normal = np.array([np.cos(alpha), np.sin(alpha)])
    sigma_n = math.sqrt(normal @ cov @ normal)
    expected = 0.5 - np.linalg.det(cov) / (2.0 * sigma_n**3 * radius * math.sqrt(2.0 * math.pi))

    got = gaussian_mass_over_disk(cov, radius * normal, radius)

    assert abs(got - expected) < 1e-9, f"{got} vs {expected}"


@pytest.mark.parametrize("deg", [0.0, 25.0, 90.0, 160.0])
def test_a_needle_covariance_reduces_to_the_mass_on_one_chord(deg):
    """sigma = 1e-4 m across the needle and 30 m along it. Across, the
    Gaussian is a delta, so Pc is the 1D mass of N(m_y, sigma_y^2) on the
    chord at x = m_x, whose half-height is h = sqrt(R^2 - m_x^2):

        Pc = Phi((h - m_y) / sigma_y) - Phi((-h - m_y) / sigma_y)

    in principal axes. The remainder is O(sigma_x^2 / sigma_y^2), ~1e-11."""
    radius, sigma_x, sigma_y = 20.0, 1e-4, 30.0
    m = np.array([5.0, 3.0])
    h = math.sqrt(radius**2 - m[0] ** 2)
    expected = ndtr((h - m[1]) / sigma_y) - ndtr((-h - m[1]) / sigma_y)

    rot = _rotation(deg)
    got = gaussian_mass_over_disk(rot @ np.diag([sigma_x**2, sigma_y**2]) @ rot.T, rot @ m, radius)

    assert abs(got - expected) < 1e-9, f"{got} vs {expected}"


@pytest.mark.parametrize(
    "sx,sy,mux,muy,radius",
    [
        (0.2, 0.5, 9.9, 0.3, 10.0),      # mean near the edge, R / sigma = 50
        (0.05, 0.05, 0.0, 9.95, 10.0),   # isotropic, just inside the top of the disk
        (0.1, 3.0, 4.0, 7.0, 10.0),      # a needle crossing the edge
        (0.3, 0.3, 10.4, 0.0, 10.0),     # just outside
    ],
)
def test_the_windowed_rule_agrees_with_the_oracle(sx, sy, mux, muy, radius):
    """A panel budget below 4 R / sigma_min sends the integral through the
    windowed rule, which the tiny-sigma cases above need. Here R / sigma is
    small enough for the Cartesian oracle to check it directly."""
    cov = np.diag([sx**2, sy**2])
    mu = np.array([mux, muy])

    got = gaussian_mass_over_disk(cov, mu, radius, panel_cap=16)
    expected = _dblquad_oracle(cov, mu, radius, window_sigmas=40.0)

    assert np.isclose(got, expected, rtol=1e-8), f"{got} vs {expected}"


def test_an_integral_beyond_double_precision_is_reported_never_estimated():
    """sigma = 1e-20 m against a 10 m disk: the whole Gaussian fits inside
    one float64 step of the quadrature variable, so no grid can place a node
    on it. The integrator must say so rather than return a number."""
    with pytest.raises(integrate.UnresolvedIntegral):
        gaussian_mass_over_disk(np.eye(2) * 1e-40, np.array([3.0, 0.0]), 10.0)
