"""The close-approach search, on relative motion whose answer is known in closed form.

The search sees only a function from time to relative state, so these
tests drive it with analytic motion - a straight-line fly-by, a periodic
oscillation - where the true TCA and miss distance are exact. That makes
the oracle independent of SGP4, which tests/screening/test_screen.py
covers separately.
"""

import math

import numpy as np
import pytest

from sentinel.screening.search import find_close_approaches


def flyby(tca_s: float, miss_km: float, speed_km_s: float):
    """Straight-line relative motion: closest at tca_s, miss_km away."""
    miss = np.array([0.0, miss_km, 0.0])
    velocity = np.array([speed_km_s, 0.0, 0.0])

    def relative_state(t_s: np.ndarray):
        t = np.asarray(t_s, float)[:, None]
        return miss + velocity * (t - tca_s), np.broadcast_to(velocity, (t.shape[0], 3))

    return relative_state


def oscillation(first_tca_s: float, period_s: float, amplitude_km: float, miss_km: float):
    """Range minima of miss_km every half period, starting at first_tca_s."""
    omega = 2 * math.pi / period_s

    def relative_state(t_s: np.ndarray):
        phase = omega * (np.asarray(t_s, float) - first_tca_s)
        dr = np.column_stack([amplitude_km * np.sin(phase), np.full_like(phase, miss_km), np.zeros_like(phase)])
        dv = np.column_stack([amplitude_km * omega * np.cos(phase), np.zeros_like(phase), np.zeros_like(phase)])
        return dr, dv

    return relative_state


def test_a_straight_line_flyby_is_found_at_its_exact_tca_and_miss():
    [found] = find_close_approaches(flyby(3600.4567, 1.234, 14.0), duration_s=86400.0, threshold_km=5.0)
    assert found.t_s == pytest.approx(3600.4567, abs=1e-6)
    assert found.miss_distance_km == pytest.approx(1.234, abs=1e-9)
    assert found.relative_speed_km_s == pytest.approx(14.0)


def test_a_head_on_pass_between_coarse_samples_is_not_missed():
    """At 15 km/s with 60 s sampling the nearest samples are 450 km away."""
    [found] = find_close_approaches(flyby(630.0, 0.5, 15.0), duration_s=3600.0, threshold_km=5.0, step_s=60.0)
    assert found.t_s == pytest.approx(630.0, abs=1e-6)
    assert found.miss_distance_km == pytest.approx(0.5, abs=1e-9)


def test_an_approach_outside_the_threshold_is_not_reported():
    assert find_close_approaches(flyby(1800.0, 5.001, 7.0), duration_s=3600.0, threshold_km=5.0) == []


def test_every_minimum_in_the_window_is_found_in_time_order():
    motion = oscillation(first_tca_s=1000.0, period_s=5800.0, amplitude_km=7000.0, miss_km=2.0)
    found = find_close_approaches(motion, duration_s=86400.0, threshold_km=5.0)
    expected = [1000.0 + k * 2900.0 for k in range(30) if 1000.0 + k * 2900.0 <= 86400.0]
    assert [f.t_s for f in found] == pytest.approx(expected, abs=1e-6)
    assert all(f.miss_distance_km == pytest.approx(2.0, abs=1e-9) for f in found)


def test_objects_already_receding_at_the_window_start_have_no_tca_in_it():
    """The closest point was before the window: that TCA belongs to the previous screening."""
    assert find_close_approaches(flyby(-10.0, 1.0, 7.0), duration_s=3600.0, threshold_km=100.0) == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"duration_s": 0.0, "threshold_km": 5.0},
        {"duration_s": 3600.0, "threshold_km": 0.0},
        {"duration_s": 3600.0, "threshold_km": 5.0, "step_s": 0.0},
        {"duration_s": 3600.0, "threshold_km": math.nan},
    ],
)
def test_a_meaningless_window_threshold_or_step_raises(kwargs):
    with pytest.raises(ValueError):
        find_close_approaches(flyby(10.0, 1.0, 7.0), **kwargs)
