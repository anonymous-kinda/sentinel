"""POST /api/screening: demonstration mode (ADR-002) over the node's element sets.

Each close approach becomes a DERIVED CDM ingested through the ordinary
conjunction path, so it appears in the event list with its Pc refused by
the engine's existing NO_COVARIANCE gate. docs/icd/screening-api.md.
"""

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.api.settings import Settings
from sentinel.clock import FixedClock
from tests.screening.conftest import SNAPSHOT, WV3, crossing_object

NOW = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
REQUEST = {"primary_norad_id": WV3, "hours": 6, "threshold_km": 10}


def open_node(tmp_path, **overrides) -> TestClient:
    objects = json.loads(SNAPSHOT.read_text())
    wv3 = next(o for o in objects if o["NORAD_CAT_ID"] == WV3)
    elements = tmp_path / "elements.json"
    elements.write_text(json.dumps([wv3, crossing_object(wv3, 90.0)]))
    settings = Settings(
        exercise=False, library=False, web_dist=None, var_dir=str(tmp_path / "var"),
        elements_path=str(elements), **overrides,
    )
    client = TestClient(create_app(settings, clock=FixedClock(NOW), start_background=False))
    client.__enter__()
    return client


@pytest.fixture
def node(tmp_path):
    client = open_node(tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture
def screened(node):
    response = node.post("/api/screening", json=REQUEST)
    assert response.status_code == 200, response.text
    return node, response.json()


def test_the_answer_says_what_it_is_and_carries_no_probability(screened):
    _, body = screened
    assert body["mode"] == "DEMONSTRATION"
    assert body["primary"] == {"norad_id": WV3, "name": "WORLDVIEW-3 (WV-3)"}
    assert body["start"] == "2026-09-24T06:00:00+00:00" and body["end"] == "2026-09-24T12:00:00+00:00"
    assert (body["hours"], body["threshold_km"], body["screened"]) == (6, 10, 1)
    assert '"pc"' not in json.dumps(body), "no probability travels with a screening answer"


def test_each_approach_becomes_a_derived_event_whose_pc_the_engine_refuses(screened):
    node, body = screened
    approaches = body["approaches"]
    assert len(approaches) >= 2
    first = approaches[0]
    assert first["secondary"] == {"norad_id": 99115, "name": "CROSSER 90 (TEST)"}
    assert 0 < first["miss_distance_km"] <= 10 and first["relative_speed_km_s"] > 0
    assert first["ingest"] == "accepted" and first["data_class"] == "DERIVED"
    assert first["assessment"] == {"method": "REFUSED", "refusal_reason": "NO_COVARIANCE"}

    events = {e["event_id"]: e for e in node.get("/api/events?scope=all").json()}
    for approach in approaches:
        event = events[approach["event_id"]]
        assert event["data_class"] == "DERIVED"
        assert event["assessment"]["method"] == "REFUSED" and event["assessment"]["pc"] is None
        assert event["assessment"]["refusal_reason"] == "NO_COVARIANCE"


def test_screening_the_same_window_again_adds_nothing(screened):
    node, first = screened
    again = node.post("/api/screening", json=REQUEST).json()
    assert [a["ingest"] for a in again["approaches"]] == ["duplicate"] * len(first["approaches"])
    assert [a["event_id"] for a in again["approaches"]] == [a["event_id"] for a in first["approaches"]]


def test_nothing_close_is_an_empty_list_not_an_error(node):
    body = node.post("/api/screening", json={**REQUEST, "threshold_km": 0.001}).json()
    assert body["approaches"] == []


def test_an_unknown_primary_is_404(node):
    response = node.post("/api/screening", json={**REQUEST, "primary_norad_id": 12345})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "UNKNOWN_PRIMARY"


@pytest.mark.parametrize(
    "change",
    [
        {"hours": 0}, {"hours": 73}, {"threshold_km": 0}, {"threshold_km": 51},
        {"primary_norad_id": "40115"}, {"primary_norad_id": None}, {"hours": True}, {"extra": 1},
    ],
)
def test_wrong_input_is_422(node, change):
    assert node.post("/api/screening", json={**REQUEST, **change}).status_code == 422


def test_hours_and_threshold_take_the_documented_defaults(node):
    body = node.post("/api/screening", json={"primary_norad_id": WV3}).json()
    assert (body["hours"], body["threshold_km"]) == (24, 5)


def test_a_read_only_node_refuses_to_screen(tmp_path):
    client = open_node(tmp_path, read_only=True)
    try:
        assert client.post("/api/screening", json=REQUEST).status_code == 403
    finally:
        client.__exit__(None, None, None)
