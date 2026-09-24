"""Lagrange interpolation of a state table: exact on polynomials, local, bounded."""

import datetime as dt

import numpy as np
import pytest
from skyfield.framelib import itrs

from sentinel.ephemeris.interpolate import LAGRANGE_DEGREE, MAX_STEP_S, LagrangeInterpolator
from sentinel.ephemeris.table import EphemerisRejected, StateTable
from sentinel.ephemeris.tabulate import tabulate
from tests.omm_snapshot import TIMESCALE, satellite

T0 = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
CREATED = dt.datetime(2026, 9, 23, 22, 37, tzinfo=dt.UTC)
RNG = np.random.default_rng(20260924)


def table_of(times_s, positions_km):
    epochs = tuple(T0 + dt.timedelta(seconds=float(s)) for s in times_s)
    return StateTable(norad_id=99001, name="EXSAT-1 (EXERCISE)", epochs=epochs,
                      positions_km=positions_km, created=CREATED)


def degree8(times_s):
    """A degree-8 polynomial per axis: Lagrange degree 8 must reproduce it."""
    x = times_s / 1000.0
    return np.stack([x ** 8 - 3 * x ** 5 + 7, 2 * x ** 7 + x, -(x ** 8) + 4 * x ** 3 - x], axis=1)


def uneven_times(count):
    """Uneven steps, whole milliseconds so the table's datetime epochs are exact."""
    return np.round(np.cumsum(np.concatenate([[0.0], RNG.uniform(40.0, 80.0, count - 1)])), 3)


def test_the_default_degree_is_eight():
    assert LAGRANGE_DEGREE == 8


def test_a_polynomial_of_the_interpolation_degree_is_reproduced():
    times = uneven_times(30)
    interpolator = LagrangeInterpolator(table_of(times, degree8(times)))
    queries = RNG.uniform(0.0, times[-1], 200)
    assert interpolator.positions_km(queries) == pytest.approx(degree8(queries), rel=1e-9, abs=1e-9)


def test_the_tabulated_states_are_returned_at_their_own_epochs():
    times = uneven_times(20)
    positions = RNG.normal(0.0, 7000.0, (20, 3))
    table = table_of(times, positions)
    interpolator = LagrangeInterpolator(table)
    own_epochs_s = [interpolator.seconds(epoch) for epoch in table.epochs]
    assert np.array_equal(interpolator.positions_km(own_epochs_s), positions)


def test_the_window_slides_so_distant_states_do_not_matter():
    # A global polynomial through every state would be wrecked by the jump.
    times = np.arange(40) * 60.0
    positions = degree8(times)
    positions[30:] += 1.0e6
    interpolator = LagrangeInterpolator(table_of(times, positions))
    queries = np.linspace(0.0, times[20], 101)
    assert interpolator.positions_km(queries) == pytest.approx(degree8(queries), rel=1e-9, abs=1e-9)


def test_it_refuses_to_extrapolate():
    times = np.arange(12) * 60.0
    interpolator = LagrangeInterpolator(table_of(times, degree8(times)))
    interpolator.positions_km([0.0, times[-1]])
    for outside in (-0.001, times[-1] + 0.001):
        with pytest.raises(ValueError, match="extrapolate"):
            interpolator.positions_km([outside])


def test_it_converts_between_datetimes_and_table_seconds():
    times = np.arange(12) * 60.0
    interpolator = LagrangeInterpolator(table_of(times, degree8(times)))
    when = T0 + dt.timedelta(seconds=90.25)
    assert interpolator.seconds(when) == 90.25
    assert interpolator.when(90.25) == when
    assert interpolator.stop_s == 660.0


def test_a_table_shorter_than_one_window_is_rejected():
    times = np.arange(LAGRANGE_DEGREE) * 60.0
    with pytest.raises(EphemerisRejected) as caught:
        LagrangeInterpolator(table_of(times, degree8(times)))
    assert caught.value.code == "TOO_FEW_STATES"


def test_a_gap_wider_than_the_maximum_step_is_rejected():
    times = np.arange(20) * 60.0
    times[10:] += MAX_STEP_S
    with pytest.raises(EphemerisRejected) as caught:
        LagrangeInterpolator(table_of(times, degree8(times)))
    assert caught.value.code == "STEP_TOO_COARSE"


@pytest.mark.parametrize(
    "step_s,interior_m,outermost_m", [(60.0, 0.001, 0.001), (MAX_STEP_S, 1.0, 15.0)]
)
def test_leo_positions_between_states_are_accurate_up_to_the_maximum_step(step_s, interior_m, outermost_m):
    # Against Skyfield SGP4 directly, every 5 s over 6 h. In the outermost four
    # intervals the window cannot be centred, so the error there is larger:
    # 15 m is still 2 ms of along-track motion.
    wv3 = satellite(40115)
    table = tabulate(wv3, TIMESCALE, T0, T0 + dt.timedelta(hours=6), step_s=step_s)
    interpolator = LagrangeInterpolator(table)
    query_s = np.arange(0.0, interpolator.stop_s, 5.0)
    truth = wv3.at(TIMESCALE.from_datetimes([T0 + dt.timedelta(seconds=s) for s in query_s])).frame_xyz(itrs).km.T
    error_m = np.linalg.norm(interpolator.positions_km(query_s) - truth, axis=1) * 1000.0
    edge_s = (LAGRANGE_DEGREE // 2) * step_s
    interior = (query_s >= edge_s) & (query_s <= interpolator.stop_s - edge_s)
    assert error_m[interior].max() < interior_m
    assert error_m.max() < outermost_m
