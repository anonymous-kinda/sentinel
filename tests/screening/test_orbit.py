"""An element set as an orbit: SGP4 through Skyfield, and the frames it speaks.

SGP4 works in TEME. The CDM needs an inertial frame the engine accepts
(GCRF). Range is the same in both, because at any instant both objects
are rotated by the same matrix - so the search runs in TEME and only the
final states are converted. These tests pin each of those claims.
"""

import datetime as dt
import math

import numpy as np
import pytest
from skyfield.api import EarthSatellite, load

from sentinel.screening.orbit import Orbit, OrbitUnusable

from .conftest import WINDOW_START, WV3, crossing_object

MU_KM3_S2 = 398600.8  # WGS-72, the constants SGP4 uses


def angle_deg(a: np.ndarray, b: np.ndarray) -> float:
    return math.degrees(math.acos(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)), -1.0, 1.0)))


def test_an_orbit_carries_the_identity_and_epoch_of_its_element_set(snapshot):
    orbit = Orbit.from_omm(snapshot[WV3])
    assert orbit.norad_id == WV3
    assert orbit.name.startswith("WORLDVIEW-3")
    assert orbit.epoch == dt.datetime(2026, 9, 23, 22, 37, 2, 779392, tzinfo=dt.UTC)


def test_the_radial_band_is_perigee_to_apogee_of_the_mean_elements(snapshot):
    fields = snapshot[WV3]
    n_rad_s = fields["MEAN_MOTION"] * 2 * math.pi / 86400.0
    kepler_a_km = (MU_KM3_S2 / n_rad_s**2) ** (1 / 3)
    perigee_km, apogee_km = Orbit.from_omm(fields).radial_band_km
    assert perigee_km < apogee_km
    assert apogee_km - perigee_km == pytest.approx(2 * kepler_a_km * fields["ECCENTRICITY"], rel=0.01)
    assert (perigee_km + apogee_km) / 2 == pytest.approx(kepler_a_km, abs=10.0), "Kozai vs Brouwer mean motion"


def test_range_computed_in_teme_equals_range_in_skyfield_gcrs(snapshot):
    primary = snapshot[WV3]
    other = crossing_object(primary, 90.0)
    offsets_s = np.array([0.0, 1234.5, 40000.25, 86400.0])
    (r1, _), (r2, _) = (Orbit.from_omm(f).teme_km(WINDOW_START, offsets_s) for f in (primary, other))
    ts = load.timescale(builtin=True)
    t = ts.from_datetimes([WINDOW_START + dt.timedelta(seconds=float(s)) for s in offsets_s])
    gcrs = [EarthSatellite.from_omm(ts, f).at(t).position.km.T for f in (primary, other)]
    np.testing.assert_allclose(
        np.linalg.norm(r2 - r1, axis=1), np.linalg.norm(gcrs[1] - gcrs[0], axis=1), rtol=0, atol=1e-6
    )


def test_gcrf_states_are_teme_rotated_by_precession_since_j2000_not_relabelled(snapshot):
    """TEME written out as GCRF is the classic frame error: ~0.37 deg by 2026, 45 km in LEO."""
    orbit = Orbit.from_omm(snapshot[WV3])
    (r_teme,), (v_teme,) = orbit.teme_km(WINDOW_START, np.array([0.0]))
    r_gcrf, v_gcrf = orbit.gcrf_state_km(WINDOW_START)
    assert np.linalg.norm(r_gcrf) == pytest.approx(np.linalg.norm(r_teme), abs=1e-6)
    assert np.linalg.norm(v_gcrf) == pytest.approx(np.linalg.norm(v_teme), abs=1e-6)
    assert 0.30 < angle_deg(r_teme, r_gcrf) < 0.45


def test_an_element_set_skyfield_cannot_read_is_unusable(snapshot):
    fields = {k: v for k, v in snapshot[WV3].items() if k != "OBJECT_ID"}
    with pytest.raises(OrbitUnusable) as exc:
        Orbit.from_omm(fields)
    assert exc.value.code == "UNUSABLE_ELEMENTS"


def test_an_element_set_already_underground_at_epoch_is_unusable(snapshot):
    with pytest.raises(OrbitUnusable) as exc:
        Orbit.from_omm({**snapshot[WV3], "ECCENTRICITY": 0.3})
    assert exc.value.code == "UNUSABLE_ELEMENTS"


def test_an_sgp4_failure_inside_the_window_is_reported_not_propagated(snapshot):
    """SGP4 returns a position even for a decayed orbit; only its error code says it is garbage.
    At apogee at epoch this orbit is valid; its perigee, half a revolution later, is underground."""
    orbit = Orbit.from_omm({**snapshot[WV3], "ECCENTRICITY": 0.3, "MEAN_ANOMALY": 180.0})
    with pytest.raises(OrbitUnusable) as exc:
        orbit.teme_km(WINDOW_START, np.arange(0.0, 86400.0, 60.0))
    assert exc.value.code == "PROPAGATION_FAILED"
    assert "decayed" in exc.value.detail
