"""Tabulating a propagator: a StateTable DERIVED from a public element set."""

import datetime as dt

import pytest
from skyfield.framelib import itrs

from sentinel.ephemeris.tabulate import tabulate
from tests.omm_snapshot import TIMESCALE, satellite

START = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)


def test_tabulate_samples_earth_fixed_positions_at_a_fixed_step():
    wv3 = satellite(40115)
    table = tabulate(wv3, TIMESCALE, START, START + dt.timedelta(hours=1), step_s=60.0)
    assert len(table.epochs) == 61
    assert table.epochs[0] == START
    assert table.epochs[-1] == START + dt.timedelta(hours=1)
    assert table.epochs[1] - table.epochs[0] == dt.timedelta(seconds=60)
    direct = wv3.at(TIMESCALE.from_datetime(table.epochs[17])).frame_xyz(itrs).km
    assert table.positions_km[17] == pytest.approx(direct, abs=1e-9)


def test_the_table_is_named_for_the_element_set_and_dated_by_its_epoch():
    # Derived from an element set, the table knows no more than the set did:
    # its age is the element set's age, not the time this code ran.
    wv3 = satellite(40115)
    table = tabulate(wv3, TIMESCALE, START, START + dt.timedelta(minutes=10), step_s=60.0)
    assert table.norad_id == 40115
    assert table.name == "WORLDVIEW-3 (WV-3)"
    assert table.created == wv3.epoch.utc_datetime()
