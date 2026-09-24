"""The pass module's shared contract: what every pass provider returns."""

import datetime as dt

from sentinel.passes.model import PassWindow

T0 = dt.datetime(2026, 9, 24, 18, 0, tzinfo=dt.UTC)


def window(sensor="EO", sunlit=True, age_days=0.5):
    return PassWindow(
        norad_id=40115, name="WORLDVIEW-3 (WV-3)", sensor=sensor,
        rise=T0, culmination=T0 + dt.timedelta(minutes=4), set=T0 + dt.timedelta(minutes=8),
        max_elevation_deg=61.0, mask_elevation_deg=40.3, element_age_days=age_days,
        sunlit=sunlit if sensor == "EO" else None, provider="test",
    )


def test_a_window_is_padded_by_element_set_age():
    w = window(age_days=2.0)
    assert w.pad_s == 120.0
    assert w.padded == (T0 - dt.timedelta(seconds=120), T0 + dt.timedelta(minutes=8, seconds=120))


def test_old_element_sets_are_stale():
    assert not window(age_days=2.9).stale
    assert window(age_days=3.1).stale


def test_optical_imagers_need_daylight_and_radar_does_not():
    assert window("EO", sunlit=True).usable
    assert not window("EO", sunlit=False).usable
    assert window("SAR").usable
