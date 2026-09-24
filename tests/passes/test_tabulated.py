"""The tabulated-ephemeris pass provider: behaviour specific to working from tables.

Behaviour every provider shares is in tests/conformance/; accuracy against a
brute-force Skyfield oracle is there too.
"""

import dataclasses
import datetime as dt
import logging

import numpy as np
import pytest
from skyfield.api import wgs84
from skyfield.framelib import itrs

from sentinel.ephemeris.table import EphemerisRejected, StateTable
from sentinel.ephemeris.tabulate import tabulate
from sentinel.passes.geometry import EARTH_RADIUS_KM, min_elevation_deg, sun_elevation_deg
from sentinel.passes.model import Imager, ImagerNotCovered, PassWindow, Unit
from sentinel.passes.providers.tabulated import TabulatedEphemerisProvider
from tests.omm_snapshot import TIMESCALE, satellite

UNIT = Unit("NTC", 35.26, -116.68)
START = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
END = START + dt.timedelta(hours=24)
WV3 = Imager(40115, "WORLDVIEW-3", "EO", 45.0, basis="test assumption")
S1A = Imager(39634, "SENTINEL-1A", "SAR", 45.0, basis="test assumption")
TABLE_START = START - dt.timedelta(hours=1)
TABLE_STOP = END + dt.timedelta(hours=1)
LOGGER = "sentinel.passes.providers.tabulated"


@pytest.fixture(scope="module")
def tables():
    return {
        norad_id: tabulate(satellite(norad_id), TIMESCALE, TABLE_START, TABLE_STOP, step_s=60.0)
        for norad_id in (WV3.norad_id, S1A.norad_id)
    }


@pytest.fixture(scope="module")
def wv3_windows(tables):
    windows = TabulatedEphemerisProvider(tables).windows(UNIT, [WV3], START, END)
    assert windows, "the scenario must contain WORLDVIEW-3 windows or these tests prove nothing"
    return windows


def skyfield_elevation_deg(norad_id, when):
    topos = wgs84.latlon(UNIT.lat_deg, UNIT.lon_deg, elevation_m=UNIT.alt_m)
    return (satellite(norad_id) - topos).at(TIMESCALE.from_datetime(when)).altaz()[0].degrees


def warnings_named(caplog, message):
    return [r for r in caplog.records if r.name == LOGGER and r.getMessage() == message]


def test_the_provider_names_itself_on_every_window(tables, wv3_windows):
    provider = TabulatedEphemerisProvider(tables)
    assert provider.name == "tabulated-ephemeris"
    assert all(isinstance(w, PassWindow) and w.provider == "tabulated-ephemeris" for w in wv3_windows)
    assert all(w.name == "WORLDVIEW-3 (WV-3)" and w.norad_id == 40115 for w in wv3_windows)


def test_rise_and_set_are_where_the_elevation_crosses_the_mask_to_a_tenth_of_a_second(wv3_windows):
    half = dt.timedelta(seconds=0.05)
    for w in wv3_windows:
        assert skyfield_elevation_deg(40115, w.rise - half) < w.mask_elevation_deg < skyfield_elevation_deg(40115, w.rise + half)
        assert skyfield_elevation_deg(40115, w.set - half) > w.mask_elevation_deg > skyfield_elevation_deg(40115, w.set + half)


def test_culmination_is_the_highest_point_of_the_pass(wv3_windows):
    for w in wv3_windows:
        for offset_s in (-1.0, 1.0):
            neighbour = skyfield_elevation_deg(40115, w.culmination + dt.timedelta(seconds=offset_s))
            assert neighbour < w.max_elevation_deg
        assert skyfield_elevation_deg(40115, w.culmination) == pytest.approx(w.max_elevation_deg, abs=1e-4)


def test_the_mask_comes_from_the_field_of_regard_at_the_altitude_of_culmination(tables, wv3_windows):
    for w in wv3_windows:
        position = satellite(40115).at(TIMESCALE.from_datetime(w.culmination)).frame_xyz(itrs).km
        radius_km = np.linalg.norm(position)
        expected = min_elevation_deg(WV3.max_off_nadir_deg, radius_km - EARTH_RADIUS_KM)
        assert w.mask_elevation_deg == pytest.approx(expected, abs=1e-6)


def test_the_age_is_the_age_of_the_ephemeris_product_at_culmination(tables, wv3_windows):
    created = tables[40115].created
    for w in wv3_windows:
        assert w.element_age_days == pytest.approx((w.culmination - created).total_seconds() / 86400.0, abs=1e-9)


def test_optical_windows_are_lit_when_the_sun_clears_the_configured_elevation(tables):
    default = TabulatedEphemerisProvider(tables).windows(UNIT, [WV3], START, END)
    for w in default:
        assert w.sunlit == (sun_elevation_deg(w.culmination, UNIT.lat_deg, UNIT.lon_deg) >= 10.0)
    always = TabulatedEphemerisProvider(tables, min_sun_elevation_deg=-90.0).windows(UNIT, [WV3], START, END)
    never = TabulatedEphemerisProvider(tables, min_sun_elevation_deg=90.1).windows(UNIT, [WV3], START, END)
    assert [w.sunlit for w in always] == [True] * len(default)
    assert [w.sunlit for w in never] == [False] * len(default)


def test_the_default_sun_threshold_is_ten_degrees(tables):
    assert TabulatedEphemerisProvider(tables).min_sun_elevation_deg == 10.0


def test_radar_windows_carry_no_sunlight_verdict(tables):
    windows = TabulatedEphemerisProvider(tables).windows(UNIT, [S1A], START, END)
    assert windows
    assert all(w.sunlit is None for w in windows)


def test_an_imager_with_no_table_is_refused_not_silently_dropped(tables):
    stranger = Imager(99999, "NOBODY", "EO", 45.0)
    with pytest.raises(ImagerNotCovered) as exc:
        TabulatedEphemerisProvider(tables).windows(UNIT, [stranger], START, END)
    assert exc.value.norad_id == 99999


def test_it_never_extrapolates_and_says_when_the_table_is_short(tables, wv3_windows, caplog):
    full = tables[40115]
    cut = START + dt.timedelta(hours=18)
    inside = [w for w in wv3_windows if w.set <= cut]
    assert inside and len(inside) < len(wv3_windows), "the cut must fall between windows to prove anything"
    keep = [i for i, epoch in enumerate(full.epochs) if epoch <= cut]
    short = dataclasses.replace(full, epochs=full.epochs[: len(keep)], positions_km=full.positions_km[keep])
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        windows = TabulatedEphemerisProvider({40115: short}).windows(UNIT, [WV3], START, END)
    assert len(windows) == len(inside)
    for got, want in zip(windows, inside):
        assert abs((got.rise - want.rise).total_seconds()) < 0.01
        assert abs((got.set - want.set).total_seconds()) < 0.01
    (record,) = warnings_named(caplog, "Ephemeris does not cover interval")
    assert record.fields["norad_id"] == 40115
    assert record.fields["table_stop"] == cut.isoformat()
    assert record.fields["requested_end"] == END.isoformat()


def test_a_pass_cut_by_the_edge_of_the_table_is_not_reported_but_is_warned_about(tables, wv3_windows, caplog):
    # The table starts after the pass has risen: its true rise is unknowable.
    target = max(wv3_windows, key=lambda w: w.set - w.rise)
    full = tables[40115]
    keep = [i for i, epoch in enumerate(full.epochs) if epoch > target.rise]
    cut = dataclasses.replace(full, epochs=tuple(full.epochs[i] for i in keep), positions_km=full.positions_km[keep])
    assert target.rise < cut.start < target.set
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        windows = TabulatedEphemerisProvider({40115: cut}).windows(UNIT, [WV3], cut.start, target.set)
    assert windows == []
    (record,) = warnings_named(caplog, "Pass extends beyond searched ephemeris")
    assert record.fields["norad_id"] == 40115


def test_a_table_filed_under_another_catalog_number_is_rejected(tables):
    with pytest.raises(EphemerisRejected) as caught:
        TabulatedEphemerisProvider({39634: tables[40115]})
    assert caught.value.code == "NORAD_ID_MISMATCH"


def test_a_table_too_coarse_to_interpolate_is_rejected_at_construction(tables):
    full: StateTable = tables[40115]
    coarse = dataclasses.replace(full, epochs=full.epochs[::10], positions_km=full.positions_km[::10])
    with pytest.raises(EphemerisRejected) as caught:
        TabulatedEphemerisProvider({40115: coarse})
    assert caught.value.code == "STEP_TOO_COARSE"
