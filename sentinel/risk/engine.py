"""The assessment entry point.

Orchestration only: the applicability gate, TCA refinement, the collision
integral, and dilution detection. The maths lives in frames.py,
geometry.py, encounter.py and integrate.py so each piece can be tested on
its own - and so the UI can draw the same encounter plane the engine used.

The gate runs before any probability is returned. Refusing is a feature -
the engine declines to produce a number the linear encounter model does not
support, records which condition tripped and at what value, and still
reports the geometry that is honestly derivable without covariance.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .encounter import (
    build_encounter_plane,
    curvilinear_check,
    linear_tca_adjustment_s,
    relative_state,
)
from .geometry import tca_residual
from .integrate import gaussian_mass_over_disk, maximize_pc_over_scale
from .types import (
    AssessedConjunction,
    AssessmentConfig,
    Conjunction,
    Method,
    ObjectState,
    RefusalReason,
)


def _resolve_hbr(
    conjunction: Conjunction, config: AssessmentConfig
) -> tuple[float | None, bool]:
    """Combined hard-body radius, and whether a configured default was used."""
    defaulted = False
    radii = []
    for state in (conjunction.primary, conjunction.secondary):
        radius = state.radius_m
        if radius is None:
            if config.default_radius_m is None:
                return None, False
            radius = config.default_radius_m
            defaulted = True
        radii.append(float(radius))
    return sum(radii), defaulted


def _min_eigenvalue(covariance: np.ndarray) -> float:
    cov = np.asarray(covariance, dtype=float)
    cov = 0.5 * (cov + cov.T)
    return float(np.min(np.linalg.eigvalsh(cov)))


def _asymmetry(covariance: np.ndarray) -> float:
    cov = np.asarray(covariance, dtype=float)
    scale = np.max(np.abs(cov)) or 1.0
    return float(np.max(np.abs(cov - cov.T)) / scale)


def assess(
    conjunction: Conjunction, config: AssessmentConfig | None = None
) -> AssessedConjunction:
    """Assess one conjunction. Never raises on bad data; refuses instead."""
    config = config or AssessmentConfig()

    primary: ObjectState = conjunction.primary
    secondary: ObjectState = conjunction.secondary

    # Geometry first: it is derivable without covariance, so it is reported
    # even on refusal.
    rel0 = relative_state(conjunction)
    miss_distance_m = rel0.miss_distance_m
    relative_speed_m_s = rel0.speed_m_s

    inputs_hash = conjunction.inputs_hash()
    hbr_m, hbr_defaulted = _resolve_hbr(conjunction, config)

    base_diagnostics = {
        "independence_assumed": True,
        "hbr_defaulted": hbr_defaulted,
    }

    def refuse(reason: RefusalReason, **extra: Any) -> AssessedConjunction:
        return AssessedConjunction(
            method=Method.REFUSED,
            pc=None,
            pc_max=None,
            dilution_flag=False,
            dilution_margin=None,
            miss_distance_m=miss_distance_m,
            relative_speed_m_s=relative_speed_m_s,
            hbr_m=hbr_m,
            inputs_hash=inputs_hash,
            refusal_reason=reason,
            diagnostics={**base_diagnostics, **extra},
        )

    # --- gate: covariance present ----------------------------------------
    if primary.covariance_rtn_m2 is None or secondary.covariance_rtn_m2 is None:
        missing = [
            state.object_id
            for state in (primary, secondary)
            if state.covariance_rtn_m2 is None
        ]
        return refuse(RefusalReason.NO_COVARIANCE, missing_covariance_for=missing)

    # --- gate: hard-body radius resolvable -------------------------------
    if hbr_m is None:
        return refuse(RefusalReason.NO_HBR, default_radius_m=config.default_radius_m)

    # --- gate: supplied covariances are valid ----------------------------
    supplied = ((primary, primary.covariance_rtn_m2), (secondary, secondary.covariance_rtn_m2))
    for state, covariance in supplied:
        smallest = _min_eigenvalue(covariance)
        if smallest <= 0.0:
            return refuse(
                RefusalReason.INVALID_COVARIANCE,
                min_eigenvalue=smallest,
                object_id=state.object_id,
                stage="input_covariance",
            )

    # --- gate: relative velocity supports the rectilinear model -----------
    if relative_speed_m_s < config.min_relative_speed_m_s:
        return refuse(
            RefusalReason.LOW_RELATIVE_VELOCITY,
            relative_speed_m_s=relative_speed_m_s,
            threshold=config.min_relative_speed_m_s,
        )

    # --- gate: the supplied state is at (rounded) closest approach -------
    dt_s = linear_tca_adjustment_s(rel0)
    residual_m = tca_residual(rel0.position_m, rel0.velocity_m_s)
    if abs(dt_s) > config.max_tca_adjustment_s:
        return refuse(
            RefusalReason.TCA_INCONSISTENT,
            tca_adjustment_s=dt_s,
            tca_residual_m=residual_m,
            threshold=config.max_tca_adjustment_s,
        )

    # --- steps 1-4: refine TCA, unify frames, combine, project -----------
    plane = build_encounter_plane(conjunction, hbr_m, refine_tca=config.refine_tca)
    cov_2d = plane.cov_2d_m2
    mu = plane.mu_m

    eigenvalues = np.linalg.eigvalsh(cov_2d)
    if np.any(eigenvalues <= 0.0):
        return refuse(
            RefusalReason.INVALID_COVARIANCE,
            min_eigenvalue=float(np.min(eigenvalues)),
            stage="projected_covariance",
        )

    condition_number = float(np.max(eigenvalues) / np.min(eigenvalues))
    if condition_number > config.max_condition_number:
        return refuse(
            RefusalReason.ILL_CONDITIONED_COVARIANCE,
            condition_number=condition_number,
            threshold=config.max_condition_number,
        )

    # --- gate: uncertainty is flat enough for a planar Gaussian ----------
    curvature = curvilinear_check(conjunction, plane)
    if curvature.ratio > config.max_curvilinear_ratio:
        return refuse(
            RefusalReason.CURVILINEAR_UNCERTAINTY,
            curvilinear_ratio=curvature.ratio,
            along_track_sagitta_m=curvature.sagitta_m,
            encounter_sigma_min_m=curvature.sigma_min_m,
            object_id=curvature.object_id,
            threshold=config.max_curvilinear_ratio,
            requires="3D Nc (curvilinear) assessment; not implemented, see risk-engine-design.md s8",
        )

    # --- step 5: integrate ------------------------------------------------
    pc = gaussian_mass_over_disk(cov_2d, mu, hbr_m, panel_cap=config.quadrature_panels_cap)

    # --- steps 6 & 7: worst case over covariance scaling, and dilution ----
    k_star, pc_max, hit_bound = maximize_pc_over_scale(
        cov_2d, mu, hbr_m, panel_cap=config.quadrature_panels_cap
    )
    diluted = k_star < 1.0

    return AssessedConjunction(
        method=Method.FOSTER_ESTES_2D,
        pc=pc,
        pc_max=pc_max,
        dilution_flag=bool(diluted),
        dilution_margin=math.log(k_star),
        miss_distance_m=plane.relative.miss_distance_m,
        relative_speed_m_s=relative_speed_m_s,
        hbr_m=hbr_m,
        inputs_hash=inputs_hash,
        refusal_reason=None,
        diagnostics={
            **base_diagnostics,
            "k_star": k_star,
            "k_star_at_search_bound": hit_bound,
            "projected_eigenvalues_m2": eigenvalues.tolist(),
            "condition_number": condition_number,
            "tca_adjustment_s": plane.tca_adjustment_s,
            "curvilinear_ratio": curvature.ratio,
            "tca_residual_m": residual_m,
            "miss_distance_at_supplied_tca_m": miss_distance_m,
            "covariance_asymmetry": max(
                _asymmetry(primary.covariance_rtn_m2),
                _asymmetry(secondary.covariance_rtn_m2),
            ),
            "projected_miss_m": mu.tolist(),
        },
    )
