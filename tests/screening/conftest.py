"""Shared fixtures: the public snapshot, and a close approach built from it.

`crossing_object` derives a second object from a real snapshot element set
so that the two orbits are guaranteed to meet: the same orbit rotated in
right ascension of the ascending node, with the mean anomaly shifted so
both objects reach the line where the planes intersect at the same time.
Same size, shape and inclination means the same secular drift, so they
keep meeting there - twice a revolution - for the whole window.

`brute_force_minima` is the oracle: range sampled every second straight
from Skyfield's SGP4 model, then every millisecond around each minimum.
It shares no code with sentinel.screening.
"""

from __future__ import annotations

import datetime as dt
import math
import pathlib

import numpy as np
import pytest
from skyfield.api import EarthSatellite, load

from sentinel.passes.element_store import ElementStore

SNAPSHOT = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "omm" / "celestrak-resource-20260924.json"
WV3 = 40115
WINDOW_START = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
DAY_S = 86400.0


@pytest.fixture(scope="session")
def snapshot() -> dict[int, dict]:
    store = ElementStore()
    store.load_snapshot(SNAPSHOT, "celestrak")
    return store.latest()


def _plane_normal(inclination: float, raan: float) -> np.ndarray:
    return np.array([math.sin(inclination) * math.sin(raan), -math.sin(inclination) * math.cos(raan), math.cos(inclination)])


def _argument_of_latitude_deg(point: np.ndarray, inclination: float, raan: float) -> float:
    node = np.array([math.cos(raan), math.sin(raan), 0.0])
    ninety_past_node = np.cross(_plane_normal(inclination, raan), node)
    return math.degrees(math.atan2(point @ ninety_past_node, point @ node))


def crossing_object(base: dict, raan_offset_deg: float, norad_id: int = 99115) -> dict:
    inclination = math.radians(base["INCLINATION"])
    raan_1 = math.radians(base["RA_OF_ASC_NODE"])
    raan_2 = math.radians(base["RA_OF_ASC_NODE"] + raan_offset_deg)
    line = np.cross(_plane_normal(inclination, raan_1), _plane_normal(inclination, raan_2))
    shift_deg = _argument_of_latitude_deg(line, inclination, raan_2) - _argument_of_latitude_deg(line, inclination, raan_1)
    return {
        **base,
        "NORAD_CAT_ID": norad_id,
        "OBJECT_NAME": f"CROSSER {raan_offset_deg:g} (TEST)",
        "OBJECT_ID": "2099-001A",
        "RA_OF_ASC_NODE": (base["RA_OF_ASC_NODE"] + raan_offset_deg) % 360.0,
        "MEAN_ANOMALY": (base["MEAN_ANOMALY"] + shift_deg) % 360.0,
    }


def _utc_jd(when: dt.datetime) -> tuple[float, float]:
    days = (when - dt.datetime(2000, 1, 1, 12, tzinfo=dt.UTC)).total_seconds() / DAY_S
    whole = math.floor(days)
    return 2451545.0 + whole, days - whole


def range_km(a: dict, b: dict, start: dt.datetime, t_s: np.ndarray) -> np.ndarray:
    """Range between two element sets at start + t_s, straight from Skyfield's SGP4 model."""
    ts = load.timescale(builtin=True)
    jd, fraction = _utc_jd(start)
    positions = []
    for fields in (a, b):
        errors, r, _ = EarthSatellite.from_omm(ts, fields).model.sgp4_array(np.full_like(t_s, jd), fraction + t_s / DAY_S)
        assert not errors.any(), "the oracle needs a clean propagation"
        positions.append(r)
    return np.linalg.norm(positions[1] - positions[0], axis=1)


def brute_force_minima(a: dict, b: dict, start: dt.datetime, hours: float, threshold_km: float) -> list[tuple[float, float]]:
    """(TCA seconds from start, miss km) of every range minimum below threshold_km.

    1 s sampling finds each minimum to within a second; 1 ms sampling of the
    two seconds around it then pins TCA to 0.5 ms and the miss distance to
    centimetres. A 1 s sample can sit up to 7.5 km above the true minimum
    at 15 km/s, so candidates are taken with that margin, then filtered.
    """
    coarse_t = np.arange(0.0, hours * 3600.0 + 1.0, 1.0)
    coarse = range_km(a, b, start, coarse_t)
    interior = np.flatnonzero((coarse[1:-1] <= coarse[:-2]) & (coarse[1:-1] < coarse[2:])) + 1
    minima = []
    for i in interior[coarse[interior] <= threshold_km + 8.0]:
        fine_t = np.arange(coarse_t[i] - 1.0, coarse_t[i] + 1.0005, 0.001)
        fine = range_km(a, b, start, fine_t)
        j = int(np.argmin(fine))
        if fine[j] <= threshold_km:
            minima.append((float(fine_t[j]), float(fine[j])))
    return minima
