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
half-height h(x) = sqrt(R^2 - x^2). The first axis is the narrow one
(eigh sorts ascending), so the numerical integral carries the sharpest
factor and the analytic one the gentler.

That remaining integrand has an infinite derivative at x = +/- R, which
ordinary quadrature handles badly. Substituting x = R cos(theta) removes it,
giving a smooth integrand over theta in [0, pi]. This is the same device
behind CARA's Gauss-Chebyshev formulation.

Two node rules, and a proof that they worked
--------------------------------------------
When the disk is much larger than the uncertainty, the integrand is a spike
of width ~sigma / R in theta. A grid that steps over it returns a plausible,
wrong answer.

- The uniform rule spreads 4 R / sigma_min composite Gauss-Legendre panels
  over [0, pi], about 0.8 sigma per panel. It is the rule validated against
  CARA, and it is used whenever that many panels fit in `panel_cap`.
- Beyond the cap, the windowed rule integrates only where the integrand
  lives. The Gaussian factor is below exp(-800), under the smallest float64,
  more than 40 sigma_x from m_x, so the window discards nothing
  representable. Inside the window the erf factor turns over only where the
  chord's half-height is within 40 sigma_y of |m_y|; those turning points
  split the window into at most five pieces, and each piece gets the same
  fixed number of panels. The cost no longer grows with R / sigma.

Neither rule is taken on trust. The same nodes integrate the Gaussian
factor alone, the x-marginal N(m_x, sigma_x^2) over the disk's x-extent,
whose value has a closed form. A grid that missed the spike misses that
mass too. When the two disagree, typically because sigma is so far below
R that the spike fits inside one float64 step of theta, the integrator
raises UnresolvedIntegral rather than return a number.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import erf, erfc

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)

_POINTS_PER_PANEL = 16
_MIN_PANELS = 16
_DEFAULT_PANEL_CAP = 4096

# Beyond 40 sigma a Gaussian factor is below exp(-800); float64 stops at
# about exp(-745), so a window this wide loses nothing it could represent.
_WINDOW_SIGMAS = 40.0
# A piece of the window spans at most 4 * _WINDOW_SIGMAS sigma of either
# factor (the worst case is a window that ends at theta = 0 or pi, where
# x = R cos(theta) is quadratic). This many panels keeps each 16-point panel
# within 0.25 sigma, fine enough to integrate a Gaussian tail 40 sigma out.
_PANELS_PER_PIECE = 16 * int(_WINDOW_SIGMAS)

# The resolution check. A missed spike is an O(1) error; the tolerance sits
# far above rounding and far below that. The absolute term is a few ulps of
# 1: below it, no Pc error could matter to a decision.
_MARGINAL_RTOL = 1e-6
_MARGINAL_ATOL = 1e-15

_Nodes = tuple[np.ndarray, np.ndarray]

_uniform_cache: dict[int, _Nodes] = {}


class UnresolvedIntegral(ArithmeticError):
    """The quadrature could not resolve the integrand in double precision.

    `sigma_min` is the smallest principal sigma of the covariance that was
    being integrated, in the caller's length unit.
    """

    def __init__(self, sigma_min: float) -> None:
        super().__init__("collision integral not resolved in double precision")
        self.sigma_min = sigma_min


def _gauss_legendre(edges: np.ndarray) -> _Nodes:
    """Composite Gauss-Legendre nodes and weights, one rule per panel
    between consecutive edges."""
    nodes, weights = np.polynomial.legendre.leggauss(_POINTS_PER_PANEL)
    lo = edges[:-1][:, None]
    hi = edges[1:][:, None]
    half = 0.5 * (hi - lo)
    mid = 0.5 * (hi + lo)
    return (mid + half * nodes[None, :]).ravel(), (half * weights[None, :]).ravel()


def _uniform_nodes(n_panels: int) -> _Nodes:
    """`n_panels` equal panels over [0, pi]."""
    cached = _uniform_cache.get(n_panels)
    if cached is None:
        cached = _gauss_legendre(np.linspace(0.0, math.pi, n_panels + 1))
        _uniform_cache[n_panels] = cached
    return cached


def _theta_at_x(x: float, radius: float) -> float:
    """theta with R cos(theta) = x, clipped to the disk."""
    return math.acos(min(max(x / radius, -1.0), 1.0))


def _theta_at_half_height(h: float, radius: float) -> float:
    """theta in [0, pi/2] with R sin(theta) = h, clipped to the disk."""
    return math.asin(min(max(h / radius, 0.0), 1.0))


def _window_breaks(m: np.ndarray, sigma_x: float, sigma_y: float, radius: float) -> list[float]:
    """Where in theta the integrand lives, split where its erf factor turns.

    Outside the turning zone, |h - |m_y|| > 40 sigma_y, the erf factor is 0
    or 2 to double precision. One break means an empty window: the Gaussian
    lies more than 40 sigma_x beyond the disk.
    """
    reach_x = _WINDOW_SIGMAS * sigma_x
    start = _theta_at_x(float(m[0]) + reach_x, radius)
    stop = _theta_at_x(float(m[0]) - reach_x, radius)
    reach_y = _WINDOW_SIGMAS * sigma_y
    near = _theta_at_half_height(abs(float(m[1])) - reach_y, radius)
    far = _theta_at_half_height(abs(float(m[1])) + reach_y, radius)
    turns = (near, far, math.pi - far, math.pi - near)
    return sorted({start, stop, *(t for t in turns if start < t < stop)})


def _windowed_nodes(m: np.ndarray, sigma_x: float, sigma_y: float, radius: float) -> _Nodes:
    """A fixed number of panels on each piece of the window."""
    breaks = _window_breaks(m, sigma_x, sigma_y, radius)
    pieces = [
        np.linspace(a, b, _PANELS_PER_PIECE + 1)[:-1] for a, b in zip(breaks, breaks[1:])
    ]
    return _gauss_legendre(np.concatenate([*pieces, [breaks[-1]]]))


def _quadrature_nodes(
    m: np.ndarray, sigma_x: float, sigma_y: float, radius: float, panel_cap: int
) -> _Nodes:
    """The uniform rule when its panel count fits the cap, else the windowed rule."""
    panels_needed = 4.0 * radius / min(sigma_x, sigma_y)
    if panels_needed <= panel_cap:
        return _uniform_nodes(max(math.ceil(panels_needed), _MIN_PANELS))
    return _windowed_nodes(m, sigma_x, sigma_y, radius)


def _normal_mass(lo: float, hi: float) -> float:
    """Phi(hi) - Phi(lo) for lo <= hi, standard normal, without cancellation
    in either tail."""
    if lo >= 0.0:
        return 0.5 * float(erfc(lo / _SQRT2) - erfc(hi / _SQRT2))
    if hi <= 0.0:
        return 0.5 * float(erfc(-hi / _SQRT2) - erfc(-lo / _SQRT2))
    return 0.5 * float(erf(hi / _SQRT2) - erf(lo / _SQRT2))


def _require_resolved(
    weight: np.ndarray,
    gaussian: np.ndarray,
    h: np.ndarray,
    m_x: float,
    sigma_x: float,
    radius: float,
) -> None:
    """Raise UnresolvedIntegral unless the nodes carried the Gaussian factor.

    The x-marginal, N(m_x, sigma_x^2) over [-R, R], is integrated on the same
    nodes and compared with its closed form. The comparison is written so
    that a NaN fails it.
    """
    quadrature = float(np.sum(weight * gaussian * h)) / (sigma_x * _SQRT2PI)
    exact = _normal_mass((-radius - m_x) / sigma_x, (radius - m_x) / sigma_x)
    if not abs(quadrature - exact) <= _MARGINAL_RTOL * exact + _MARGINAL_ATOL:
        raise UnresolvedIntegral(sigma_min=sigma_x)


def gaussian_mass_over_disk(
    covariance_2d: np.ndarray,
    mean: np.ndarray,
    radius: float,
    panel_cap: int = _DEFAULT_PANEL_CAP,
) -> float:
    """Mass of N(mean, covariance_2d) over the disk of `radius` at the origin.

    All arguments share one length unit; the engine works in metres.
    `panel_cap` bounds the uniform rule; beyond it the windowed rule runs.
    Raises ValueError if the covariance is not positive definite - repairing
    it silently would be exactly the kind of invisible failure this project
    argues against - and UnresolvedIntegral if the quadrature cannot resolve
    the integrand in double precision.
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

    theta, weight = _quadrature_nodes(m, sigma_x, sigma_y, radius, panel_cap)

    x = radius * np.cos(theta)
    h = radius * np.sin(theta)

    inner = erf((h - m[1]) / (sigma_y * _SQRT2)) - erf((-h - m[1]) / (sigma_y * _SQRT2))
    gaussian = np.exp(-0.5 * ((x - m[0]) / sigma_x) ** 2)
    _require_resolved(weight, gaussian, h, float(m[0]), sigma_x, radius)
    integrand = gaussian * inner * h

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

    With the miss vector outside the disk, Pc(k) is unimodal in k: at small
    k a tight uncertainty ellipse that does not overlap the disk catches
    almost no probability mass, and at large k the mass is spread so thin
    that the disk again catches almost none. Between the two lies a maximum,
    which is the worst case over all possible scalings of the supplied
    covariance.

    With the miss vector inside the (closed) disk there is no search to do.
    The disk is convex, so it is star-shaped about the mean: if
    mu + t z lies in it, so does mu + s z for every s < t. The event
    {mu + sqrt(k) Z in disk} shrinks as k grows, so Pc(k) never rises, and
    the maximum over the bounds is at the lower one. Searching instead finds
    an arbitrary point of the plateau where Pc rounds to 1.

    `hit_bound` is True when the optimum sits at a search boundary rather
    than at an interior turning point. It is diagnostic information, not an
    answer. Raises UnresolvedIntegral if Pc cannot be resolved at a scale
    the search needs.
    """
    cov = np.asarray(covariance_2d, dtype=float)

    if _inside_disk(mean, radius):
        k_lo = bounds[0]
        return k_lo, gaussian_mass_over_disk(k_lo * cov, mean, radius, panel_cap=panel_cap), True

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


def _inside_disk(mean: np.ndarray, radius: float) -> bool:
    mu = np.asarray(mean, dtype=float)
    return math.hypot(float(mu[0]), float(mu[1])) <= radius
