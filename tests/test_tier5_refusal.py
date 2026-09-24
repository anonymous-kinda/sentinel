"""Tier 5 - the model applicability gate.

Refusing is a feature. The engine must decline to produce a number the
linear encounter model does not support, and must say which condition
tripped and at what value.

Rungs 19-23 of the ladder.
"""

import numpy as np
import pytest

from sentinel.risk.engine import assess
from sentinel.risk.types import AssessmentConfig, Method, RefusalReason

from .conftest import make_conjunction

pytestmark = pytest.mark.tier5


# --- rung 19 --------------------------------------------------------------
def test_low_relative_velocity_is_refused():
    """Near-matched velocities break the rectilinear assumption. This is the
    geostationary / similar-orbit case."""
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    slow = conj.replace(
        secondary=conj.secondary.replace(
            velocity_km_s=conj.primary.velocity_km_s + np.array([0.0, 0.0, 1e-4])
        )
    )

    result = assess(slow)

    assert result.method is Method.REFUSED
    assert result.refusal_reason is RefusalReason.LOW_RELATIVE_VELOCITY
    assert result.pc is None
    assert result.pc_max is None


def test_low_relative_velocity_threshold_is_configurable():
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)

    # Default config assesses this 15 km/s encounter happily.
    assert assess(conj).method is Method.FOSTER_ESTES_2D

    # Raise the floor above the actual relative speed and it must refuse.
    strict = AssessmentConfig(min_relative_speed_m_s=20_000.0)
    assert assess(conj, strict).refusal_reason is RefusalReason.LOW_RELATIVE_VELOCITY


# --- rung 20 --------------------------------------------------------------
def test_non_positive_definite_covariance_is_refused_not_repaired():
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    bad_cov = np.diag([2500.0, 2500.0, -1.0])  # negative eigenvalue
    bad = conj.replace(primary=conj.primary.replace(covariance_rtn_m2=bad_cov))

    result = assess(bad)

    assert result.method is Method.REFUSED
    assert result.refusal_reason is RefusalReason.INVALID_COVARIANCE
    assert result.pc is None


def test_zero_covariance_is_refused():
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    zeroed = conj.replace(
        primary=conj.primary.replace(covariance_rtn_m2=np.zeros((3, 3))),
        secondary=conj.secondary.replace(covariance_rtn_m2=np.zeros((3, 3))),
    )

    result = assess(zeroed)

    assert result.method is Method.REFUSED
    assert result.refusal_reason is RefusalReason.INVALID_COVARIANCE


# --- rung 21 --------------------------------------------------------------
def test_missing_covariance_is_refused_with_no_fallback():
    """ADR-002: demonstration mode has no covariance, therefore no Pc. The
    engine must not invent one from element-set heuristics."""
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    no_cov = conj.replace(secondary=conj.secondary.replace(covariance_rtn_m2=None))

    result = assess(no_cov)

    assert result.method is Method.REFUSED
    assert result.refusal_reason is RefusalReason.NO_COVARIANCE
    assert result.pc is None
    assert result.pc_max is None
    # Geometry is still reported - it is honestly derivable without covariance.
    assert result.miss_distance_m == pytest.approx(100.0, rel=1e-6)
    assert result.relative_speed_m_s == pytest.approx(15_000.0, rel=1e-9)


# --- rung 22 --------------------------------------------------------------
def test_ill_conditioned_covariance_is_refused():
    """A covariance spanning many orders of magnitude between its principal
    axes makes the projected inverse numerically meaningless."""
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    stretched = np.diag([1e-14, 1e10, 1e10])
    bad = conj.replace(
        primary=conj.primary.replace(covariance_rtn_m2=stretched),
        secondary=conj.secondary.replace(covariance_rtn_m2=stretched),
    )

    result = assess(bad)

    assert result.method is Method.REFUSED
    assert result.refusal_reason is RefusalReason.ILL_CONDITIONED_COVARIANCE


# --- missing hard-body radius --------------------------------------------
def test_missing_radius_is_refused_when_no_default_configured():
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    no_r = conj.replace(primary=conj.primary.replace(radius_m=None))

    result = assess(no_r)

    assert result.method is Method.REFUSED
    assert result.refusal_reason is RefusalReason.NO_HBR


def test_missing_radius_uses_configured_default_when_policy_allows():
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    no_r = conj.replace(primary=conj.primary.replace(radius_m=None))

    result = assess(no_r, AssessmentConfig(default_radius_m=5.0))

    assert result.method is Method.FOSTER_ESTES_2D
    assert result.hbr_m == pytest.approx(10.0)
    assert result.diagnostics["hbr_defaulted"] is True


# --- rung 23 --------------------------------------------------------------
def test_every_refusal_records_the_value_that_tripped_it():
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)

    slow = conj.replace(
        secondary=conj.secondary.replace(velocity_km_s=conj.primary.velocity_km_s.copy())
    )
    r = assess(slow)
    assert "relative_speed_m_s" in r.diagnostics
    assert "threshold" in r.diagnostics

    bad_cov = conj.replace(
        primary=conj.primary.replace(covariance_rtn_m2=np.diag([2500.0, 2500.0, -1.0]))
    )
    r = assess(bad_cov)
    assert "min_eigenvalue" in r.diagnostics

    offset = conj.replace(
        secondary=conj.secondary.replace(
            position_km=conj.secondary.position_km + np.array([0.0, 5.0, 0.0])
        )
    )
    r = assess(offset)
    assert "tca_residual_m" in r.diagnostics
    assert "threshold" in r.diagnostics


# --- TCA refinement --------------------------------------------------------
def test_millisecond_rounded_tca_is_refined_not_refused():
    """A CDM's TCA is rounded to the millisecond. Half a millisecond of
    along-track offset at 15 km/s is 7.5 m - refine it, don't refuse it."""
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    rounded = conj.replace(
        secondary=conj.secondary.replace(
            position_km=conj.secondary.position_km + np.array([0.0, -0.0075, 0.0])
        )
    )

    result = assess(rounded)

    assert result.method is Method.FOSTER_ESTES_2D
    assert result.diagnostics["tca_adjustment_s"] == pytest.approx(-0.0005, rel=1e-9)
    assert result.miss_distance_m == pytest.approx(100.0, rel=1e-9)
    assert result.diagnostics["miss_distance_at_supplied_tca_m"] > 100.0
    assert result.pc == pytest.approx(assess(conj).pc, rel=1e-12)


def test_tca_adjustment_limit_is_configurable():
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    offset = conj.replace(
        secondary=conj.secondary.replace(
            position_km=conj.secondary.position_km + np.array([0.0, -0.0075, 0.0])
        )
    )
    strict = AssessmentConfig(max_tca_adjustment_s=1e-4)
    result = assess(offset, strict)
    assert result.refusal_reason is RefusalReason.TCA_INCONSISTENT
    assert result.diagnostics["threshold"] == 1e-4


# --- curvilinear uncertainty ----------------------------------------------
def test_long_curved_along_track_uncertainty_is_refused():
    """300 km of along-track sigma on a 7000 km orbit bends ~6.4 km at one
    sigma - far larger than a 50 m encounter-plane sigma. The planar
    Gaussian the 2D method integrates does not describe that object."""
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    banana = np.diag([1250.0, 300_000.0**2, 1250.0])
    curved = conj.replace(secondary=conj.secondary.replace(covariance_rtn_m2=banana))

    result = assess(curved)

    assert result.method is Method.REFUSED
    assert result.refusal_reason is RefusalReason.CURVILINEAR_UNCERTAINTY
    d = result.diagnostics
    radius_m = np.linalg.norm(curved.secondary.position_km) * 1000.0
    assert d["along_track_sagitta_m"] == pytest.approx(300_000.0**2 / (2 * radius_m))
    assert d["curvilinear_ratio"] > d["threshold"]
    assert d["object_id"] == "SECONDARY"
    assert result.pc is None


def test_curvilinear_threshold_is_configurable():
    conj = make_conjunction(miss_m=100.0, sigma_m=50.0)
    assert assess(conj).diagnostics["curvilinear_ratio"] < 1e-3
    assert (
        assess(conj, AssessmentConfig(max_curvilinear_ratio=1e-9)).refusal_reason
        is RefusalReason.CURVILINEAR_UNCERTAINTY
    )
