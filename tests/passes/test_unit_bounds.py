"""A unit the node cannot compute for is refused at the door.

Only the lower bound of the reaction time and neither bound of the
altitude were checked. A reaction time of 1e13 minutes was stored, then
every GET /api/passes raised OverflowError (a 500) until someone replaced
the unit, restarts included, since the unit is persisted. An altitude of
1e300 m was accepted and answered with passes computed for a point far
outside the solar system.
"""

import datetime as dt
import pathlib

import pytest
from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.api.settings import Settings
from sentinel.clock import FixedClock
from sentinel.passes.service import MAX_HOURS
from sentinel.passes.unit import MAX_ALT_M, MIN_ALT_M, UnitRejected, unit_from_dict

SNAPSHOT = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "omm" / "celestrak-resource-20260924.json"
NOW = dt.datetime(2026, 9, 24, 6, 0, 30, tzinfo=dt.UTC)
VALID = {"unit_id": "EX-UNIT-1", "lat_deg": 35.26, "lon_deg": -116.68, "alt_m": 700.0, "reaction_time_min": 30.0}


@pytest.mark.parametrize("change,field", [
    ({"reaction_time_min": 1e13}, "reaction_time_min"),
    ({"reaction_time_min": 1e300}, "reaction_time_min"),
    ({"reaction_time_min": MAX_HOURS * 60 + 1}, "reaction_time_min"),
    ({"alt_m": 1e300}, "alt_m"),
    ({"alt_m": -1e7}, "alt_m"),
    ({"alt_m": MAX_ALT_M + 1}, "alt_m"),
    ({"alt_m": MIN_ALT_M - 1}, "alt_m"),
])
def test_a_unit_outside_what_the_node_can_compute_is_rejected_naming_the_field(change, field):
    with pytest.raises(UnitRejected) as exc:
        unit_from_dict({**VALID, **change})
    assert exc.value.field == field


def test_the_bounds_themselves_are_valid():
    unit_from_dict({**VALID, "reaction_time_min": MAX_HOURS * 60, "alt_m": MAX_ALT_M})
    unit_from_dict({**VALID, "alt_m": MIN_ALT_M})


def test_a_reaction_time_the_node_cannot_count_is_a_422_not_a_stored_500(tmp_path):
    settings = Settings(exercise=False, library=False, web_dist=None, var_dir=str(tmp_path), elements_path=str(SNAPSHOT))
    app = create_app(settings, clock=FixedClock(NOW), start_background=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        put = client.put("/api/passes/unit", json={**VALID, "reaction_time_min": 1e13})
        passes = client.get("/api/passes?hours=24")
    assert put.status_code == 422 and put.json()["detail"]["field"] == "reaction_time_min"
    assert passes.status_code == 409, "no unit was stored"
