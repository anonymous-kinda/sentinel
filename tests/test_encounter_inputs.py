"""The encounter plane on a covariance it cannot use.

The engine gates a missing covariance before it builds a plane and returns
a refusal (tier 5). These pin what the geometry helpers themselves do when
called directly, as the console's views do: without a covariance they raise
ValueError, never return a matrix; with one beyond float64 they return a
non-finite matrix for the gate to reject, quietly.
"""

import json

import pytest

from sentinel.risk.encounter import build_encounter_plane, combined_covariance_eci_m2
from sentinel.risk.engine import assess, finite_eigenvalues
from sentinel.risk.types import RefusalReason

from .conftest import make_conjunction

SIDES = ("primary", "secondary")


def without_covariance(side: str):
    conjunction = make_conjunction(miss_m=100.0, sigma_m=50.0)
    state = getattr(conjunction, side)
    return conjunction.replace(**{side: state.replace(covariance_rtn_m2=None)})


@pytest.mark.parametrize("side", SIDES)
def test_building_a_plane_without_a_covariance_raises(side):
    with pytest.raises(ValueError, match="both objects need a covariance"):
        build_encounter_plane(without_covariance(side), hbr_m=10.0)


@pytest.mark.parametrize("side", SIDES)
def test_combining_covariances_without_one_raises(side):
    with pytest.raises(ValueError):
        combined_covariance_eci_m2(without_covariance(side))


@pytest.mark.filterwarnings("error::RuntimeWarning")
@pytest.mark.parametrize("value", [1e308, -1e308])
@pytest.mark.parametrize("sides", [("primary",), ("secondary",), SIDES], ids=["primary", "secondary", "both"])
def test_an_overflowing_covariance_is_contained_and_left_to_the_gate(value, sides):
    """A 1e308 m^2 variance overflows while the projected covariance is
    formed. The overflow is expected data, not a fault: it leaves a
    non-finite matrix, finite_eigenvalues rejects it, and every caller
    refuses (the engine) or reports the view unavailable (the console's
    encounter view, which builds the plane directly). The filter turns a
    RuntimeWarning printed on the way into a failure."""
    conjunction = make_conjunction(miss_m=100.0, sigma_m=50.0)
    changes = {}
    for side in sides:
        state = getattr(conjunction, side)
        covariance = state.covariance_rtn_m2.copy()
        covariance[0, 0] = covariance[2, 2] = value  # radial and cross-track: both in the plane
        changes[side] = state.replace(covariance_rtn_m2=covariance)
    hostile = conjunction.replace(**changes)

    plane = build_encounter_plane(hostile, hbr_m=10.0)

    assert finite_eigenvalues(plane.cov_2d_m2) is None
    result = assess(hostile)
    assert result.refusal_reason is RefusalReason.INVALID_COVARIANCE
    json.dumps(result.to_dict(), allow_nan=False)
