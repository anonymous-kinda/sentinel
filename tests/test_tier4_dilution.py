"""Tier 4 - maximum Pc and dilution-region detection.

This is the tier that carries the project's central claim, so the
expectations are anchored to closed-form asymptotics rather than to
previous output.

Asymptotic result used throughout (isotropic covariance, HBR small relative
to both sigma and the miss distance, so the Gaussian is near-constant across
the disk):

    Pc(s) ~= (R^2 / 2s) * exp(-d^2 / 2s)          s = sigma^2

    dPc/ds = 0  ->  s* = d^2 / 2

    hence   k*  = s* / s0     = (d^2 / 2) / sigma0^2
            Pc_max            = R^2 / (e * d^2)
            diluted  <=>  sigma0 > d / sqrt(2)

That last line is the whole argument in one inequality: once the 1-sigma
uncertainty exceeds the miss distance over root two, adding uncertainty
*lowers* the reported collision probability.

Rungs 14-18 of the ladder.
"""

import math

import numpy as np
import pytest

from sentinel.risk import integrate
from sentinel.risk.engine import assess
from sentinel.risk.integrate import gaussian_mass_over_disk, maximize_pc_over_scale
from sentinel.risk.types import Method

from .conftest import make_conjunction

pytestmark = pytest.mark.tier4


# --- rung 14 --------------------------------------------------------------
def test_pc_is_unimodal_in_covariance_scale():
    """Sweep k over twelve orders of magnitude; the sequence of Pc values
    must rise then fall exactly once.

    Restricted to the range where Pc is representable. Below roughly
    k = 0.02 this geometry drives Pc under 1e-310 and float64 flushes it to
    exactly zero, producing a flat plateau. A plateau is not a turning
    point - it is the exponent range running out - so including it would
    test the floating-point format rather than the model.
    """
    cov = np.eye(2) * 50.0**2
    mu = np.array([300.0, 0.0])

    ks = np.logspace(-6, 6, 400)
    pcs = np.array([gaussian_mass_over_disk(k * cov, mu, 5.0) for k in ks])

    representable = pcs > 0.0
    assert representable.sum() > 200, "sweep must cover the interesting region"
    pcs = pcs[representable]

    diffs = np.diff(pcs)
    assert np.all(diffs != 0.0), "no flat segments should remain after filtering"

    sign_changes = np.sum(np.diff(np.sign(diffs)) != 0)
    assert sign_changes == 1, f"expected one turning point, found {sign_changes}"


def test_peak_of_the_sweep_sits_where_the_closed_form_predicts():
    """Independent of the optimiser: the brute-force sweep must peak at
    k* = (d^2 / 2) / sigma0^2."""
    d, sigma, hbr = 300.0, 50.0, 5.0
    cov = np.eye(2) * sigma**2
    mu = np.array([d, 0.0])

    ks = np.logspace(-2, 4, 2000)
    pcs = np.array([gaussian_mass_over_disk(k * cov, mu, hbr) for k in ks])

    peak_k = ks[np.argmax(pcs)]
    expected = (d**2 / 2.0) / sigma**2

    # Grid spacing over six decades at 2000 points is ~0.7 percent per step.
    assert np.isclose(peak_k, expected, rtol=0.01), f"{peak_k} vs {expected}"


# --- rung 15 --------------------------------------------------------------
@pytest.mark.parametrize("miss,sigma", [(100.0, 50.0), (500.0, 40.0), (50.0, 300.0)])
def test_pc_max_is_never_below_pc(miss, sigma):
    result = assess(make_conjunction(miss_m=miss, sigma_m=sigma, radius_m=2.5))
    assert result.method is Method.FOSTER_ESTES_2D
    assert result.pc_max >= result.pc


# --- analytic anchors -----------------------------------------------------
def test_optimal_scale_matches_closed_form():
    """k* = (d^2 / 2) / sigma0^2 in the small-HBR isotropic limit."""
    d, sigma, hbr = 1000.0, 400.0, 1.0
    cov = np.eye(2) * sigma**2
    mu = np.array([d, 0.0])

    k_star, _, _ = maximize_pc_over_scale(cov, mu, hbr)
    expected = (d**2 / 2.0) / sigma**2

    assert np.isclose(k_star, expected, rtol=1e-3), f"{k_star} vs {expected}"


def test_maximum_pc_matches_closed_form():
    """Pc_max = R^2 / (e * d^2) in the small-HBR isotropic limit."""
    d, sigma, hbr = 1000.0, 400.0, 1.0
    cov = np.eye(2) * sigma**2
    mu = np.array([d, 0.0])

    _, pc_max, _ = maximize_pc_over_scale(cov, mu, hbr)
    expected = hbr**2 / (np.e * d**2)

    assert np.isclose(pc_max, expected, rtol=1e-3), f"{pc_max} vs {expected}"


# --- rung 16 --------------------------------------------------------------
def test_tight_covariance_is_not_flagged_as_diluted():
    """sigma well below d/sqrt(2): more uncertainty would raise Pc, so the
    reported value is bounded above and is trustworthy in that sense."""
    d = 1000.0
    sigma = 0.3 * d / np.sqrt(2.0)

    result = assess(make_conjunction(miss_m=d, sigma_m=sigma, radius_m=0.5))

    assert result.dilution_flag is False
    assert result.diagnostics["k_star"] > 1.0
    assert result.dilution_margin > 0.0


# --- rung 17 --------------------------------------------------------------
def test_inflated_covariance_is_flagged_as_diluted():
    """sigma well above d/sqrt(2): more uncertainty *lowers* Pc."""
    d = 1000.0
    sigma = 4.0 * d / np.sqrt(2.0)

    result = assess(make_conjunction(miss_m=d, sigma_m=sigma, radius_m=0.5))

    assert result.dilution_flag is True
    assert result.diagnostics["k_star"] < 1.0
    assert result.dilution_margin < 0.0


def test_dilution_boundary_sits_at_sigma_equals_miss_over_root_two():
    """Scan sigma across the predicted boundary and confirm the flag flips
    there, not somewhere else."""
    d = 1000.0
    boundary = d / np.sqrt(2.0)

    below = assess(make_conjunction(miss_m=d, sigma_m=0.9 * boundary, radius_m=0.5))
    above = assess(make_conjunction(miss_m=d, sigma_m=1.1 * boundary, radius_m=0.5))

    assert below.dilution_flag is False
    assert above.dilution_flag is True


# --- rung 18: the headline test ------------------------------------------
def test_inflating_covariance_by_one_order_of_magnitude_lowers_pc_and_sets_flag():
    """THE HEADLINE TEST.

    Start from a conjunction whose covariance is tight enough that the
    dilution flag is clear. Inflate the covariance by one order of magnitude
    - that is, degrade the quality of the orbit determination - and observe
    that the reported probability of collision goes DOWN while the dilution
    flag comes UP.

    A consumer looking only at Pc would read the second case as safer than
    the first. It is not safer. It is less well known.

    Geometry is chosen so the start point sits just left of the Pc peak
    (k* = 1.2) and the inflated point sits well right of it (k* = 0.12):

        sigma0^2 = d^2 / 2.4   ->   k*_before = (d^2/2) / (d^2/2.4) = 1.2
        sigma1^2 = 10 sigma0^2 ->   k*_after  = 1.2 / 10             = 0.12
    """
    d = 1000.0
    sigma0 = d / np.sqrt(2.4)
    sigma1 = sigma0 * np.sqrt(10.0)  # variance x10

    before = assess(make_conjunction(miss_m=d, sigma_m=sigma0, radius_m=0.5))
    after = assess(make_conjunction(miss_m=d, sigma_m=sigma1, radius_m=0.5))

    # Both are assessable; neither is refused.
    assert before.method is Method.FOSTER_ESTES_2D
    assert after.method is Method.FOSTER_ESTES_2D

    # The pathology: worse data, lower reported risk.
    assert after.pc < before.pc, f"expected Pc to fall: {before.pc} -> {after.pc}"

    # And the flag catches it.
    assert before.dilution_flag is False
    assert after.dilution_flag is True

    # The upper bound does not fall - it is unchanged, because the true
    # worst case over covariance scaling does not depend on the scale you
    # happened to start from.
    assert np.isclose(before.pc_max, after.pc_max, rtol=1e-6)

    # Which is the point: Pc dropped, but the worst case did not.
    assert after.pc_max > after.pc


# --- a miss inside the hard-body disk --------------------------------------
# The disk is convex, so it is star-shaped about any mean inside it: if
# mu + t z lies in the disk, so does mu + s z for every s < t. The event
# {mu + sqrt(k) Z in disk} therefore shrinks as k grows, Pc(k) never rises
# with k, and the maximum over [k_lo, k_hi] sits at k_lo. The sweep reaches
# sigma far below R, where a fixed grid cannot see the spike.

INSIDE_COV = np.diag([100.0, 400.0])
INSIDE_MU = np.array([5.0, 3.0])       # 5.8 m from the centre of a 20 m disk
INSIDE_HBR = 20.0


def test_pc_at_a_tiny_scale_with_the_miss_inside_the_disk_is_one():
    """At k = 1e-12 the widest sigma is 2e-5 m and the nearest edge 14.2 m
    away, so the mass is 1 to double precision. The grid returned 6.5e-35."""
    got = gaussian_mass_over_disk(1e-12 * INSIDE_COV, INSIDE_MU, INSIDE_HBR)
    assert got == pytest.approx(1.0, abs=1e-12)


def test_pc_never_rises_with_scale_when_the_miss_is_inside_the_disk():
    """Allowance: where Pc rounds to 1 (k below ~1e-6), R / sigma reaches
    2e6 and x = R cos(theta) carries ~1e-16 R of rounding, 2e-10 sigma per
    node, which moves Pc by ~1e-12. The failure this guards against moved it
    by 35 orders of magnitude."""
    ks = np.logspace(-12, 12, 97)
    pcs = np.array([gaussian_mass_over_disk(k * INSIDE_COV, INSIDE_MU, INSIDE_HBR) for k in ks])
    assert np.all(np.diff(pcs) <= 1e-10), pcs


def test_a_miss_inside_the_disk_puts_the_maximum_at_the_lower_search_bound():
    """The optimiser used to report an interior k* = 3.2e-9, hit_bound False."""
    k_star, pc_max, hit_bound = maximize_pc_over_scale(INSIDE_COV, INSIDE_MU, INSIDE_HBR)

    assert k_star == pytest.approx(1e-12, rel=1e-9)
    assert hit_bound is True
    assert pc_max == pytest.approx(1.0, abs=1e-12)


def test_the_engine_reports_a_miss_inside_the_hard_body_at_the_search_bound():
    """3 m miss, 10 m combined hard-body radius: more uncertainty can only
    lower Pc, so the operating point is on the falling side (diluted), and
    the worst case is the whole disk."""
    result = assess(make_conjunction(miss_m=3.0, sigma_m=50.0, radius_m=5.0))

    assert result.method is Method.FOSTER_ESTES_2D
    assert result.diagnostics["k_star_at_search_bound"] is True
    assert result.diagnostics["k_star"] == pytest.approx(1e-12, rel=1e-9)
    assert result.dilution_flag is True
    assert result.dilution_margin == pytest.approx(math.log(1e-12))
    assert result.pc_max == pytest.approx(1.0, abs=1e-12)


def test_a_search_that_reaches_an_unresolvable_scale_says_so():
    """At k = 1e-40 sigma is 1e-19 m against a 20 m disk: beyond double
    precision. The search must not quietly treat that Pc as a number."""
    with pytest.raises(integrate.UnresolvedIntegral):
        maximize_pc_over_scale(INSIDE_COV, INSIDE_MU, INSIDE_HBR, bounds=(1e-40, 1e12))
