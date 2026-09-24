"""StateTable: the tabulated-ephemeris provider's input, and what it admits."""

import datetime as dt

import numpy as np
import pytest

from sentinel.ephemeris.table import (
    EphemerisRejected,
    StateTable,
    require_earth_fixed,
    require_utc,
)

T0 = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
CREATED = dt.datetime(2026, 9, 23, 22, 37, tzinfo=dt.UTC)


def epochs(count, step_s=60.0):
    return tuple(T0 + dt.timedelta(seconds=i * step_s) for i in range(count))


def table(epoch_list=None, positions=None, created=CREATED):
    epoch_list = epochs(3) if epoch_list is None else epoch_list
    positions = np.ones((len(epoch_list), 3)) * 7000.0 if positions is None else positions
    return StateTable(norad_id=40115, name="WORLDVIEW-3 (WV-3)", epochs=epoch_list,
                      positions_km=positions, created=created)


def rejected_code(build):
    with pytest.raises(EphemerisRejected) as caught:
        build()
    return caught.value.code


def test_a_table_holds_its_states_and_reports_its_span():
    t = table(epochs(5))
    assert t.positions_km.shape == (5, 3)
    assert t.start == T0
    assert t.stop == T0 + dt.timedelta(minutes=4)


def test_a_table_is_immutable():
    t = table()
    with pytest.raises(ValueError):
        t.positions_km[0, 0] = 1.0


def test_epochs_that_do_not_increase_are_rejected_because_interpolation_would_be_wrong():
    repeated = (T0, T0 + dt.timedelta(seconds=60), T0 + dt.timedelta(seconds=60))
    backwards = (T0, T0 + dt.timedelta(seconds=120), T0 + dt.timedelta(seconds=60))
    assert rejected_code(lambda: table(repeated)) == "EPOCHS_NOT_INCREASING"
    assert rejected_code(lambda: table(backwards)) == "EPOCHS_NOT_INCREASING"


def test_positions_must_be_one_xyz_row_per_epoch():
    assert rejected_code(lambda: table(epochs(3), np.ones((2, 3)))) == "SHAPE_MISMATCH"
    assert rejected_code(lambda: table(epochs(3), np.ones((3, 2)))) == "SHAPE_MISMATCH"


def test_a_table_needs_a_span():
    assert rejected_code(lambda: table(epochs(1))) == "TOO_FEW_STATES"


def test_non_finite_positions_are_rejected():
    positions = np.ones((3, 3))
    positions[1, 2] = np.nan
    assert rejected_code(lambda: table(epochs(3), positions)) == "MALFORMED_NUMBER"


def test_times_without_a_zone_are_rejected_rather_than_guessed():
    naive = tuple(e.replace(tzinfo=None) for e in epochs(3))
    assert rejected_code(lambda: table(naive)) == "NAIVE_TIME"
    assert rejected_code(lambda: table(created=CREATED.replace(tzinfo=None))) == "NAIVE_TIME"


@pytest.mark.parametrize("frame", ["ITRF", "ITRF2000", "ITRF-93", "ITRF-97", "ITRF2008", "ITRF2014", "ITRF2020", "itrf2014"])
def test_itrf_realisations_are_earth_fixed(frame):
    require_earth_fixed(frame)


@pytest.mark.parametrize("frame", ["EME2000", "GCRF", "TEME", "ICRF", "TOD", "ITRFX", "", "ECEF"])
def test_any_other_frame_is_refused_because_positions_would_be_in_the_wrong_place(frame):
    assert rejected_code(lambda: require_earth_fixed(frame)) == "REF_FRAME_NOT_EARTH_FIXED"


def test_only_utc_is_admitted_because_other_time_systems_shift_every_pass():
    require_utc("UTC")
    require_utc("utc")
    for system in ("TAI", "GPS", "TT", "UT1", ""):
        assert rejected_code(lambda s=system: require_utc(s)) == "TIME_SYSTEM_NOT_UTC"


def test_a_rejection_carries_a_stable_code_and_a_readable_detail():
    error = EphemerisRejected("TIME_SYSTEM_NOT_UTC", "TIME_SYSTEM = TAI")
    assert error.code == "TIME_SYSTEM_NOT_UTC"
    assert error.detail == "TIME_SYSTEM = TAI"
    assert str(error) == "TIME_SYSTEM_NOT_UTC: TIME_SYSTEM = TAI"
    assert isinstance(error, ValueError)
