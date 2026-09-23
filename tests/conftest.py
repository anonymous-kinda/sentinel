"""Shared fixtures and geometry builders for the risk engine test ladder.

The builder below constructs a conjunction with *exactly* controllable
encounter-plane geometry, so analytic expectations are available.

Construction (verified in test_tier1_geometry.py):

    primary   r1 = [7000, 0, 0] km    v1 = [0,  7.5, 0] km/s
    secondary r2 = r1 + [d, 0, 0]     v2 = [0, -7.5, 0] km/s

    dv  = v2 - v1 = [0, -15, 0] km/s   -> encounter-plane normal z = [0,-1,0]
    dr  = [d, 0, 0]                    -> dr . z = 0 exactly (a true TCA)
    x   = dr / |dr| = [1, 0, 0]
    y   = z cross x = [0, 0, 1]

So the encounter plane is spanned by ECI x and ECI z, and the projected
miss vector is exactly (d, 0).

Both objects' RTN->ECI rotations are signed permutations of the identity for
this geometry, so a diagonal RTN covariance stays diagonal in ECI. Setting
every RTN sigma to sigma/sqrt(2) on both objects makes the *combined*
projected 2x2 covariance exactly sigma^2 * I.
"""

import numpy as np
import pytest

from sentinel.risk.types import Conjunction, ObjectState

R_PRIMARY_KM = np.array([7000.0, 0.0, 0.0])
V_PRIMARY_KM_S = np.array([0.0, 7.5, 0.0])
V_SECONDARY_KM_S = np.array([0.0, -7.5, 0.0])


def make_conjunction(miss_m, sigma_m, radius_m=5.0, sigma_secondary_m=None):
    """Build a conjunction whose projected 2D covariance is isotropic.

    miss_m   : miss distance in metres, laid along ECI x (radial)
    sigma_m  : desired combined 1-sigma in the encounter plane, metres
    radius_m : per-object hard-body radius, metres (HBR = 2 * radius_m)
    """
    if sigma_secondary_m is None:
        # Split the combined variance evenly between the two objects.
        per_object_var = (sigma_m**2) / 2.0
        var1 = var2 = per_object_var
    else:
        var1 = sigma_m**2
        var2 = sigma_secondary_m**2

    r2 = R_PRIMARY_KM + np.array([miss_m / 1000.0, 0.0, 0.0])

    return Conjunction(
        primary=ObjectState(
            object_id="PRIMARY",
            position_km=R_PRIMARY_KM.copy(),
            velocity_km_s=V_PRIMARY_KM_S.copy(),
            covariance_rtn_m2=np.eye(3) * var1,
            radius_m=radius_m,
        ),
        secondary=ObjectState(
            object_id="SECONDARY",
            position_km=r2,
            velocity_km_s=V_SECONDARY_KM_S.copy(),
            covariance_rtn_m2=np.eye(3) * var2,
            radius_m=radius_m,
        ),
    )


@pytest.fixture
def nominal_conjunction():
    """A representative LEO conjunction: 100 m miss, 50 m sigma, 10 m HBR."""
    return make_conjunction(miss_m=100.0, sigma_m=50.0, radius_m=5.0)
