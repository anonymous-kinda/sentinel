"""The pass module over HTTP, against docs/icd/passes-api.md.

Edge-local: the unit and its windows are computed and served by the node
the operator is at, from element sets already on that node. Nothing on this
interface calls another node or publishes beyond `node.<id>.`.
"""

import datetime as dt
import json
import logging
import pathlib
import stat
import time

import pytest
from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.api.settings import Settings
from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock
from sentinel.passes.service import ELEMENTS_SETTLE_S

SNAPSHOT = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "omm" / "celestrak-resource-20260924.json"
NOW = dt.datetime(2026, 9, 24, 6, 0, 30, tzinfo=dt.UTC)
UNIT = {"unit_id": "EX-UNIT-1", "lat_deg": 35.26, "lon_deg": -116.68, "alt_m": 700.0, "reaction_time_min": 30.0}
WV3 = 40115

TOP_KEYS = {"unit", "start", "end", "provider", "label", "windows", "gaps", "next_unobserved", "catalog", "elements"}
WINDOW_KEYS = {
    "norad_id", "name", "sensor", "rise", "culmination", "set", "padded_start", "padded_end", "pad_s",
    "max_elevation_deg", "mask_elevation_deg", "element_age_days", "stale", "sunlit", "usable",
}
GAP_KEYS = {"start", "end", "duration_s", "low_confidence"}
CATALOG_KEYS = {"norad_id", "name", "sensor", "max_off_nadir_deg", "gsd_m", "basis", "element_epoch", "element_age_days", "stale"}


class RecordingBus(InProcessBus):
    """Records every publish and every request a node makes."""

    def __init__(self):
        super().__init__()
        self.published: list[tuple[str, bytes]] = []
        self.requested: list[str] = []

    async def publish(self, subject, data, headers=None):
        self.published.append((subject, data))
        await super().publish(subject, data, headers)

    async def request(self, subject, data, timeout, headers=None):
        self.requested.append(subject)
        return await super().request(subject, data, timeout, headers)


def open_node(tmp_path, bus=None, **overrides) -> TestClient:
    settings = Settings(exercise=False, library=False, web_dist=None, var_dir=str(tmp_path / "var"), **overrides)
    client = TestClient(create_app(settings, clock=FixedClock(NOW), bus=bus, start_background=False))
    client.__enter__()
    return client


@pytest.fixture
def node(tmp_path):
    client = open_node(tmp_path)
    yield client
    client.__exit__(None, None, None)


@pytest.fixture
def with_unit(node):
    assert node.put("/api/passes/unit", json=UNIT).status_code == 200
    return node


# ----------------------------------------------------------------- the edge
def test_windows_are_computed_and_served_by_the_edge(tmp_path):
    bus = RecordingBus()
    edge = open_node(tmp_path, bus=bus, node_id="edge-alpha", role="edge", hub_id="hub", elements_path=str(SNAPSHOT))
    try:
        assert edge.put("/api/passes/unit", json=UNIT).status_code == 200
        response = edge.get("/api/passes?hours=24")
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "skyfield-local" and body["catalog"]["imagers"] == 38
        assert body["windows"] and body["gaps"]
    finally:
        edge.__exit__(None, None, None)
    assert bus.requested == [], "no request left the edge: nothing was asked of the hub"
    assert bus.published and all(subject.startswith("node.edge-alpha.") for subject, _ in bus.published)


def test_the_node_reports_the_pass_module(node):
    assert "passes" in node.get("/api/node").json()["modules"]


# ------------------------------------------------------------------ the unit
def test_the_unit_is_set_read_and_deleted(node, tmp_path):
    assert node.get("/api/passes/unit").status_code == 404
    put = node.put("/api/passes/unit", json=UNIT)
    assert put.status_code == 200 and put.json() == UNIT
    assert node.get("/api/passes/unit").json() == UNIT
    unit_file = tmp_path / "var" / "unit.json"
    assert stat.S_IMODE(unit_file.stat().st_mode) == 0o600
    deleted = node.delete("/api/passes/unit")
    assert deleted.status_code == 204 and deleted.content == b""
    assert node.get("/api/passes/unit").status_code == 404 and not unit_file.exists()


@pytest.mark.parametrize(
    "body,field",
    [
        ({**UNIT, "lat_deg": 90.5}, "lat_deg"),
        ({**UNIT, "lon_deg": -181.0}, "lon_deg"),
        ({**UNIT, "reaction_time_min": 0}, "reaction_time_min"),
        ({k: v for k, v in UNIT.items() if k != "unit_id"}, "unit_id"),
        ({**UNIT, "lat_deg": "north"}, "lat_deg"),
        ([UNIT], "unit"),
    ],
)
def test_wrong_input_is_422_naming_the_field(node, body, field):
    response = node.put("/api/passes/unit", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == field
    assert node.get("/api/passes/unit").status_code == 404


def test_a_body_that_is_not_json_is_422(node):
    response = node.put("/api/passes/unit", content=b"lat=35", headers={"Content-Type": "application/json"})
    assert response.status_code == 422


def test_a_read_only_node_refuses_writes(tmp_path):
    client = open_node(tmp_path, read_only=True)
    try:
        assert client.put("/api/passes/unit", json=UNIT).status_code == 403
        assert client.delete("/api/passes/unit").status_code == 403
        assert client.get("/api/passes/unit").status_code == 404
    finally:
        client.__exit__(None, None, None)


# ------------------------------------------------------------ windows, gaps
def test_passes_without_a_unit_is_409(node):
    assert node.get("/api/passes").status_code == 409


@pytest.mark.parametrize("hours", ["0.5", "73", "0", "soon"])
def test_hours_outside_1_to_72_is_422(with_unit, hours):
    assert with_unit.get(f"/api/passes?hours={hours}").status_code == 422


def test_the_answer_has_exactly_the_interface_shape(with_unit):
    body = with_unit.get("/api/passes?hours=24").json()
    assert set(body) == TOP_KEYS
    assert body["unit"] == UNIT
    assert body["start"] == "2026-09-24T06:00:00+00:00" and body["end"] == "2026-09-25T06:00:00+00:00"
    assert body["label"] == "not observed by catalogued imagers"
    assert all(set(w) == WINDOW_KEYS for w in body["windows"])
    assert all(set(g) == GAP_KEYS for g in body["gaps"])
    assert set(body["next_unobserved"]) == GAP_KEYS
    assert body["catalog"] == {"imagers": 38, "skipped": []}
    assert set(body["elements"]) == {"oldest_age_days", "newest_age_days", "stale"}


def test_windows_are_sorted_by_rise_and_include_unusable_ones(with_unit):
    windows = with_unit.get("/api/passes?hours=24").json()["windows"]
    rises = [dt.datetime.fromisoformat(w["rise"]) for w in windows]
    assert rises == sorted(rises)
    assert any(not w["usable"] for w in windows) and any(w["usable"] for w in windows)
    for w in windows:
        start, end = dt.datetime.fromisoformat(w["padded_start"]), dt.datetime.fromisoformat(w["padded_end"])
        assert start == dt.datetime.fromisoformat(w["rise"]) - dt.timedelta(seconds=w["pad_s"])
        assert end == dt.datetime.fromisoformat(w["set"]) + dt.timedelta(seconds=w["pad_s"])


def test_the_next_gap_is_long_enough_and_still_to_run(with_unit):
    gap = with_unit.get("/api/passes?hours=24").json()["next_unobserved"]
    assert gap["duration_s"] >= UNIT["reaction_time_min"] * 60
    assert dt.datetime.fromisoformat(gap["end"]) > NOW


# ------------------------------------------------------------------- catalog
def test_the_catalog_pairs_imagers_with_their_element_sets(node):
    body = node.get("/api/passes/catalog").json()
    assert set(body) == {"imagers", "skipped"} and body["skipped"] == []
    assert len(body["imagers"]) == 38 and all(set(i) == CATALOG_KEYS for i in body["imagers"])
    wv3 = next(i for i in body["imagers"] if i["norad_id"] == WV3)
    assert wv3["name"] == "WORLDVIEW-3 (WV-3)", "the element set's name, as in the windows"
    assert wv3["sensor"] == "EO" and wv3["stale"] is False


def test_an_edge_with_no_element_sets_yet_says_so(tmp_path):
    edge = open_node(tmp_path, node_id="edge-alpha", role="edge", hub_id="hub")
    try:
        catalog = edge.get("/api/passes/catalog").json()
        assert catalog["imagers"] == [] and len(catalog["skipped"]) == 38
        assert set(catalog["skipped"][0]) == {"norad_id", "name", "reason"}
        assert catalog["skipped"][0]["reason"] == "missing"
        edge.put("/api/passes/unit", json=UNIT)
        body = edge.get("/api/passes?hours=6").json()
        assert body["windows"] == [] and body["catalog"]["imagers"] == 0
        assert [g["low_confidence"] for g in body["gaps"]] == [True]
    finally:
        edge.__exit__(None, None, None)


# -------------------------------------------------------------------- tracks
def test_a_track_is_ecef_metres_at_twenty_seconds(node):
    body = node.get(
        "/api/passes/tracks",
        params={"norad_id": WV3, "start": "2026-09-24T06:00:00Z", "end": "2026-09-24T06:30:00Z"},
    ).json()
    assert set(body) == {"norad_id", "positions_ecef_m", "step_s", "note"}
    assert body["norad_id"] == WV3 and body["note"] == "visualization only"
    assert body["step_s"] == 20 and type(body["step_s"]) is int, "the interface says 20"
    assert len(body["positions_ecef_m"]) == 91
    radius_m = sum(c * c for c in body["positions_ecef_m"][0]) ** 0.5
    assert 6.9e6 < radius_m < 7.1e6


@pytest.mark.parametrize(
    "params,status",
    [
        ({"norad_id": 1, "start": "2026-09-24T06:00:00Z", "end": "2026-09-24T06:10:00Z"}, 404),
        ({"norad_id": WV3, "start": "2026-09-24T06:00:00Z", "end": "2026-09-24T06:31:00Z"}, 422),
        ({"norad_id": WV3, "start": "2026-09-24T06:10:00Z", "end": "2026-09-24T06:00:00Z"}, 422),
        ({"norad_id": WV3, "start": "2026-09-24T06:00:00", "end": "2026-09-24T06:10:00"}, 422),
        ({"norad_id": WV3, "start": "whenever", "end": "2026-09-24T06:10:00Z"}, 422),
    ],
)
def test_tracks_refuse_what_they_cannot_draw(node, params, status):
    assert node.get("/api/passes/tracks", params=params).status_code == status


# --------------------------------------------------------------- node wiring
def test_hub_and_standalone_load_the_vendored_snapshot_and_say_how_much(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    client = open_node(tmp_path, node_id="hub", role="hub")
    try:
        assert len(client.get("/api/passes/catalog").json()["imagers"]) == 38
    finally:
        client.__exit__(None, None, None)
    record = next(r for r in caplog.records if r.getMessage() == "Element sets loaded")
    assert (record.fields["accepted"], record.fields["rejected"]) == (167, 0)


def test_a_missing_snapshot_degrades_to_no_element_sets(tmp_path, caplog):
    client = open_node(tmp_path, elements_path=str(tmp_path / "absent.json"))
    try:
        assert client.get("/api/passes/catalog").json()["imagers"] == []
    finally:
        client.__exit__(None, None, None)
    assert any(r.getMessage() == "Element snapshot missing" for r in caplog.records)


def test_the_hub_serves_element_sets_through_the_same_sync_records(tmp_path):
    hub = open_node(tmp_path, node_id="hub", role="hub")
    try:
        manifest = hub.app.state.node.sync_server.records.manifest()
        assert len([entry for entry in manifest if entry["e"].startswith("omm:")]) == 167
        assert f"omm:{WV3}" in {entry["e"] for entry in manifest}
    finally:
        hub.__exit__(None, None, None)


def test_an_edge_admits_synced_element_sets_and_tells_its_console(tmp_path):
    bus = RecordingBus()
    edge = open_node(tmp_path, bus=bus, node_id="edge-alpha", role="edge", hub_id="hub")
    try:
        records = edge.app.state.node.sync_agent.records
        obj = next(o for o in json.loads(SNAPSHOT.read_text()) if o["NORAD_CAT_ID"] == WV3)
        raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
        outcome = edge.portal.call(records.ingest, raw, "sync:hub", "REAL", f"omm:{WV3}")
        assert outcome["status"] == "accepted"
        assert [i["norad_id"] for i in edge.get("/api/passes/catalog").json()["imagers"]] == [WV3]

        def updates():
            return [json.loads(data) for subject, data in bus.published if subject == "node.edge-alpha.passes.updated"]

        deadline = time.monotonic() + 5 * ELEMENTS_SETTLE_S
        while not updates() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert updates() == [{"reason": "elements", "elements_version": 1}], "once the sync burst settles"
    finally:
        edge.__exit__(None, None, None)


def test_settings_read_the_element_snapshot_path_from_the_environment(monkeypatch):
    monkeypatch.setenv("SENTINEL_ELEMENTS", "/srv/sentinel/omm.json")
    assert Settings.from_env().elements_path == "/srv/sentinel/omm.json"
    monkeypatch.delenv("SENTINEL_ELEMENTS")
    assert Settings.from_env().elements_path is None
