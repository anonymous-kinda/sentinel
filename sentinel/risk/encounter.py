"""The encounter plane: everything the 2D method needs, and nothing else.

Pure geometry, no gates. The engine decides whether the model applies;
this module only builds the objects the model operates on, so the UI can
draw the same B-plane and Pc(k) curve the engine integrated.

TCA refinement
--------------
A CDM carries each state at a TCA rounded to the millisecond, but the true
closest approach does not fall on a millisecond boundary. At 15 km/s one
millisecond is 15 m of along-track offset - comparable to a hard-body
radius. Following CARA's FindNearbyCA (linear motion mode), both states are
moved to the true linear-motion closest approach before projecting:

    dt   = -(dr . dv) / |dv|^2
    r_i' = r_i + v_i dt

Covariances are not propagated across dt. For a sub-millisecond shift the
change is far below the precision the covariance itself carries, and CARA's
reference computation (Pc2D_FromCDM) makes the same choice. A large dt is
not a rounding artefact; the engine's gate refuses it (TCA_INCONSISTENT).
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from .frames import rotate_covariance_rtn_to_eci
from .geometry import encounter_plane_basis
from .integrate import gaussian_mass_over_disk
from .types import Conjunction

_KM_TO_M = 1000.0


@dataclasses.dataclass(frozen=True, eq=False)
class RelativeState:
    """Relative position/velocity (secondary minus primary), metres."""

    position_m: np.ndarray
    velocity_m_s: np.ndarray

    @property
    def miss_distance_m(self) -> float:
        return float(np.linalg.norm(self.position_m))

    @property
    def speed_m_s(self) -> float:
        return float(np.linalg.norm(self.velocity_m_s))


@dataclasses.dataclass(frozen=True, eq=False)
class EncounterPlane:
    """The 2D problem the collision integral is evaluated on."""

    cov_2d_m2: np.ndarray        # 2x2, combined covariance projected
    mu_m: np.ndarray             # projected miss vector, (|miss|, ~0)
    hbr_m: float
    basis: np.ndarray            # rows x_hat, y_hat, z_hat in ECI
    cov_eci_m2: np.ndarray       # combined 3x3 covariance in ECI
    relative: RelativeState      # at the refined TCA
    tca_adjustment_s: float      # dt applied to reach the true TCA

    def pc(self, scale: float = 1.0, panel_cap: int = 4096) -> float:
        return gaussian_mass_over_disk(scale * self.cov_2d_m2, self.mu_m, self.hbr_m, panel_cap)

    def sigma_along_relative_velocity_m(self) -> float:
        """Combined 1-sigma position uncertainty along the relative velocity."""
        z_hat = self.basis[2]
        return float(math.sqrt(max(z_hat @ self.cov_eci_m2 @ z_hat, 0.0)))


def relative_state(conjunction: Conjunction) -> RelativeState:
    """Relative state at the supplied TCA, converted to metres."""
    p, s = conjunction.primary, conjunction.secondary
    dr = (np.asarray(s.position_km, float) - np.asarray(p.position_km, float)) * _KM_TO_M
    dv = (np.asarray(s.velocity_km_s, float) - np.asarray(p.velocity_km_s, float)) * _KM_TO_M
    return RelativeState(dr, dv)


def linear_tca_adjustment_s(rel: RelativeState) -> float:
    """Time from the supplied epoch to the linear-motion closest approach."""
    speed2 = float(rel.velocity_m_s @ rel.velocity_m_s)
    if speed2 == 0.0:
        raise ValueError("relative velocity is zero; closest approach is undefined")
    return -float(rel.position_m @ rel.velocity_m_s) / speed2


def refine_to_tca(rel: RelativeState, dt_s: float) -> RelativeState:
    return RelativeState(rel.position_m + rel.velocity_m_s * dt_s, rel.velocity_m_s)


def _require_covariances(conjunction: Conjunction) -> tuple[np.ndarray, np.ndarray]:
    """Both objects' RTN covariances. Raises ValueError if either is missing."""
    primary, secondary = conjunction.primary.covariance_rtn_m2, conjunction.secondary.covariance_rtn_m2
    if primary is None or secondary is None:
        raise ValueError("both objects need a covariance to build an encounter plane")
    return primary, secondary


def combined_covariance_eci_m2(conjunction: Conjunction) -> np.ndarray:
    """Sum of both objects' position covariances, each rotated from its own
    RTN frame to ECI. Valid if the two orbit determinations are independent."""
    p, s = conjunction.primary, conjunction.secondary
    p_cov, s_cov = _require_covariances(conjunction)
    combined: np.ndarray = rotate_covariance_rtn_to_eci(
        p_cov, p.position_km, p.velocity_km_s
    ) + rotate_covariance_rtn_to_eci(s_cov, s.position_km, s.velocity_km_s)
    return combined


def build_encounter_plane(
    conjunction: Conjunction, hbr_m: float, refine_tca: bool = True
) -> EncounterPlane:
    """Construct the encounter plane. Raises ValueError on degenerate input
    (missing covariance, zero relative velocity); the engine gates those
    cases before calling this, and returns a refusal instead."""
    _require_covariances(conjunction)

    rel0 = relative_state(conjunction)
    dt_s = linear_tca_adjustment_s(rel0) if refine_tca else 0.0
    rel = refine_to_tca(rel0, dt_s)

    x_hat, y_hat, z_hat = encounter_plane_basis(rel.position_m, rel.velocity_m_s)
    basis = np.vstack([x_hat, y_hat, z_hat])
    projection = basis[:2]

    # A variance near the float64 limit overflows here (and inf * 0 in the
    # projection makes NaN). That is data, not a fault: the matrix comes out
    # non-finite, finite_eigenvalues rejects it, and every caller refuses.
    # Silence the warning, keep the value.
    with np.errstate(over="ignore", invalid="ignore"):
        cov_eci = combined_covariance_eci_m2(conjunction)
        cov_2d = projection @ cov_eci @ projection.T
        cov_2d = 0.5 * (cov_2d + cov_2d.T)
    mu = projection @ rel.position_m

    return EncounterPlane(
        cov_2d_m2=cov_2d,
        mu_m=mu,
        hbr_m=float(hbr_m),
        basis=basis,
        cov_eci_m2=cov_eci,
        relative=rel,
        tca_adjustment_s=dt_s,
    )


def pc_curve(
    plane: EncounterPlane, log10_k: np.ndarray, panel_cap: int = 4096
) -> np.ndarray:
    """Pc as a function of covariance scale factor k, for plotting.

    Uses exactly the integrator the engine uses, so the curve on screen and
    the number in the result cannot disagree.
    """
    return np.array(
        [plane.pc(10.0 ** float(lk), panel_cap=panel_cap) for lk in np.asarray(log10_k, float)]
    )


@dataclasses.dataclass(frozen=True)
class CurvilinearCheck:
    """How far the along-track uncertainty bends at the encounter's scale."""

    ratio: float                 # max over objects of sagitta / sigma_min
    sagitta_m: float             # the larger 1-sigma along-track sagitta
    sigma_min_m: float           # smallest 1-sigma axis in the encounter plane
    object_id: str               # which object's arc bends most


def curvilinear_check(conjunction: Conjunction, plane: EncounterPlane) -> CurvilinearCheck:
    """Sagitta of each object's 1-sigma along-track arc vs the encounter plane.

    An along-track displacement s on a circular path of radius R departs
    from the tangent line by s^2 / (2R). Position uncertainty in a CDM is
    dominated by along-track error, and that error lives along the orbit,
    not along the tangent. When the bend at one sigma is comparable to the
    tightest dimension of the projected covariance, the flat Gaussian the
    2D integral assumes is a poor description of where the object can be.

    This is a screening metric, not CARA's usage-violation algorithm (which
    propagates equinoctial covariances along curvilinear trajectories). Its
    threshold is calibrated against CARA's published violation flags.
    """
    sigma_min = math.sqrt(max(float(np.min(np.linalg.eigvalsh(plane.cov_2d_m2))), 0.0))
    worst = (0.0, "")
    for state in (conjunction.primary, conjunction.secondary):
        radius_m = float(np.linalg.norm(state.position_km)) * _KM_TO_M
        sigma_t2 = float(np.asarray(state.covariance_rtn_m2, float)[1, 1])
        sagitta = max(sigma_t2, 0.0) / (2.0 * radius_m)
        if sagitta >= worst[0]:
            worst = (sagitta, state.object_id)
    ratio = worst[0] / sigma_min if sigma_min > 0.0 else math.inf
    return CurvilinearCheck(ratio, worst[0], sigma_min, worst[1])
