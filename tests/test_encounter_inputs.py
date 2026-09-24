"""The encounter plane refuses a conjunction that lacks a covariance.

The engine gates a missing covariance before it builds a plane and returns
a refusal (tier 5). These pin what the geometry helpers themselves do when
called directly without one: raise ValueError, never return a matrix.
"""

import pytest

from sentinel.risk.encounter import build_encounter_plane, combined_covariance_eci_m2

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
