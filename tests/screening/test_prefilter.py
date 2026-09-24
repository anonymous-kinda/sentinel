"""The apogee/perigee pre-filter drops a pair only when it provably cannot meet.

If two objects' radii are always more than `threshold` apart, so are the
objects: |r1 - r2| >= | |r1| - |r2| |. The filter works from mean-element
perigee and apogee, which SGP4's short-period terms overshoot, so each
band is padded. The soundness test measures that overshoot on every
object in the snapshot; the brute-force test checks the conclusion.
"""

import numpy as np
import pytest

from sentinel.screening.orbit import Orbit
from sentinel.screening.prefilter import PAD_KM, may_approach

from .conftest import WINDOW_START, WV3, range_km

GEO_RESOURCE_SAT = 41194


@pytest.mark.parametrize(
    "band_b,expected",
    [
        ((6990.0, 7000.0), True),                                   # overlapping
        ((6995.0 + 5.0 + 2 * PAD_KM, 7100.0), True),                # gap exactly threshold + pads
        ((6995.0 + 5.0 + 2 * PAD_KM + 0.001, 7100.0), False),       # just beyond
        ((6600.0, 6800.0 - 5.0 - 2 * PAD_KM - 0.001), False),       # just beyond, from below
    ],
)
def test_bands_further_apart_than_threshold_plus_pads_cannot_meet(band_b, expected):
    assert may_approach((6800.0, 6995.0), band_b, threshold_km=5.0) is expected


def test_leo_and_geo_never_meet(snapshot):
    leo, geo = Orbit.from_omm(snapshot[WV3]), Orbit.from_omm(snapshot[GEO_RESOURCE_SAT])
    assert may_approach(leo.radial_band_km, geo.radial_band_km, threshold_km=5.0) is False


def test_every_snapshot_object_stays_inside_its_padded_band_all_day(snapshot):
    """The property that makes the filter sound, measured: worst overshoot on this snapshot is ~11 km."""
    offsets_s = np.arange(0.0, 86400.0 + 1.0, 10.0)
    for norad_id, fields in snapshot.items():
        orbit = Orbit.from_omm(fields)
        radius_km = np.linalg.norm(orbit.teme_km(WINDOW_START, offsets_s)[0], axis=1)
        perigee_km, apogee_km = orbit.radial_band_km
        assert perigee_km - PAD_KM <= radius_km.min(), norad_id
        assert radius_km.max() <= apogee_km + PAD_KM, norad_id


def test_no_pair_that_brute_force_sees_within_the_threshold_is_dropped(snapshot):
    """Every object that 10 s sampling puts within 150 km of WV-3 today passes the filter.
    (Nothing comes within 5 km of WV-3 in this snapshot, so 5 km would test nothing.)"""
    threshold_km = 150.0
    primary = Orbit.from_omm(snapshot[WV3])
    offsets_s = np.arange(0.0, 86400.0 + 1.0, 10.0)
    near = [
        norad_id
        for norad_id, fields in snapshot.items()
        if norad_id != WV3 and range_km(snapshot[WV3], fields, WINDOW_START, offsets_s).min() <= threshold_km
    ]
    assert len(near) >= 5, "the check must not be vacuous"
    for norad_id in near:
        secondary = Orbit.from_omm(snapshot[norad_id])
        assert may_approach(primary.radial_band_km, secondary.radial_band_km, threshold_km), norad_id
