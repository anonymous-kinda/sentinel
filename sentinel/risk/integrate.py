"""The 2D collision integral and the maximum-Pc search.

Probability of collision is the mass of a bivariate normal over the
hard-body disk:

    Pc = 1 / (2 pi sqrt(det C)) * INT_{|u| <= R} exp(-1/2 (u-mu)' C^-1 (u-mu)) du

Reduction used here
-------------------
Eigendecompose C to principal axes, so the density factorises. The inner
integral over the second axis is then analytic:

    INT_{-h}^{h} exp(-(y-my)^2 / 2 sy^2) dy
        = sy sqrt(2 pi) / 2 * [erf((h-my)/(sy sqrt2)) - erf((-h-my)/(sy sqrt2))]

leaving a one-dimensional integral over the first axis, with the disk's
half-height h(x) = sqrt(R^2 - x^2).

That remaining integrand has an infinite derivative at x = +/- R, which
ordinary quadrature handles badly. Substituting x = R cos(theta) removes it,
giving a smooth integrand over theta in [0, pi]. This is the same device
behind CARA's Gauss-Chebyshev formulation.

Panel count is adaptive. When the disk is much larger than the uncertainty
the integrand becomes a narrow spike near theta = pi/2, and a fixed node
count silently under-resolves it - returning a plausible, wrong answer. The
panel count scales with R / sigma_min so the spike is always resolved.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import erf

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)

_POINTS_PER_PANEL = 16
_MIN_PANELS = 16
_DEFAULT_PANEL_CAP = 4096

_node_cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}


def _composite_gauss_legendre(n_panels: int) -> tuple[np.ndarray, np.ndarray]:
    """Composite Gauss-Legendre nodes and weights over [0, pi]."""
    cached = _node_cache.get(n_panels)
    if cached is not None:
        return cached

    nodes, weights = np.polynomial.legendre.leggauss(_POINTS_PER_PANEL)
    edges = np.linspace(0.0, math.pi, n_panels + 1)
    lo = edges[:-1][:, None]
    hi = edges[1:][:, None]
    half = 0.5 * (hi - lo)
    mid = 0.5 * (hi + lo)

    theta = (mid + half * nodes[None, :]).ravel()
    weight = (half * weights[None, :]).ravel()

    _node_cache[n_panels] = (theta, weight)
    return theta, weight


def gaussian_mass_over_disk(
    covariance_2d: np.ndarray,
    mean: np.ndarray,
    radius: float,
    panel_cap: int = _DEFAULT_PANEL_CAP,
) -> float:
    """Mass of N(mean, covariance_2d) over the disk of `radius` at the origin.

    All arguments share one length unit; the engine works in metres.
    Raises ValueError if the covariance is not positive definite - repairing
    it silently would be exactly the kind of invisible failure this project
    argues against.
    """
    cov = np.asarray(covariance_2d, dtype=float)
    cov = 0.5 * (cov + cov.T)  # symmetrise serialisation noise
    mu = np.asarray(mean, dtype=float)

    if radius <= 0.0:
        return 0.0

    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    if np.any(eigenvalues <= 0.0):
        raise ValueError("covariance is not positive definite")

    # Principal axes: the density factorises and the inner integral is exact.
    m = eigenvectors.T @ mu
    sigma_x = math.sqrt(eigenvalues[0])
    sigma_y = math.sqrt(eigenvalues[1])

    sigma_min = min(sigma_x, sigma_y)
    n_panels = int(np.clip(math.ceil(4.0 * radius / sigma_min), _MIN_PANELS, panel_cap))
    theta, weight = _composite_gauss_legendre(n_panels)

    x = radius * np.cos(theta)
    h = radius * np.sin(theta)

    inner = erf((h - m[1]) / (sigma_y * _SQRT2)) - erf((-h - m[1]) / (sigma_y * _SQRT2))
    integrand = np.exp(-0.5 * ((x - m[0]) / sigma_x) ** 2) * inner * h

    value = float(np.sum(weight * integrand) / (2.0 * sigma_x * _SQRT2PI))
    return min(max(value, 0.0), 1.0)


def maximize_pc_over_scale(
    covariance_2d: np.ndarray,
    mean: np.ndarray,
    radius: float,
    bounds: tuple[float, float] = (1e-12, 1e12),
    panel_cap: int = _DEFAULT_PANEL_CAP,
) -> tuple[float, float, bool]:
    """Find the covariance scale factor that maximises Pc.

    Returns (k_star, pc_max, hit_bound).

    Pc(k) is unimodal in k: at small k a tight uncertainty ellipse that does
    not overlap the disk catches almost no probability mass, and at large k
    the mass is spread so thin that the disk again catches almost none.
    Between the two lies a maximum, which is the worst case over all possible
    scalings of the supplied covariance.

    `hit_bound` is True when the optimum sits at a search boundary rather
    than at an interior turning point. That happens when the miss vector
    falls inside the hard-body disk, where Pc decreases monotonically in k.
    It is diagnostic information, not an answer.
    """
    cov = np.asarray(covariance_2d, dtype=float)
    log_lo, log_hi = math.log(bounds[0]), math.log(bounds[1])

    def negative_pc(log_k: float) -> float:
        return -gaussian_mass_over_disk(
            math.exp(log_k) * cov, mean, radius, panel_cap=panel_cap
        )

    result = minimize_scalar(
        negative_pc,
        bounds=(log_lo, log_hi),
        method="bounded",
        options={"xatol": 1e-9},
    )

    log_k_star = float(result.x)
    span = log_hi - log_lo
    hit_bound = (log_k_star - log_lo) < 1e-6 * span or (log_hi - log_k_star) < 1e-6 * span

    return math.exp(log_k_star), float(-result.fun), hit_bound
