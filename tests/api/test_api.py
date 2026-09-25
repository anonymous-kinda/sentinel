"""The node API, end to end, against a frozen clock."""

import datetime as dt
import pathlib

import pytest
from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.api.settings import Settings
from sentinel.clock import FixedClock
from sentinel.conjunction.exercise import generate

EPOCH = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.UTC)
CARA = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "cara"


@pytest.fixture
def client(tmp_path):
    settings = Settings(exercise=False, library=True, web_dist=None, var_dir=str(tmp_path))
    app = create_app(settings, clock=FixedClock(EPOCH + dt.timedelta(hours=1)), start_background=False)
    with TestClient(app) as c:
        # Load the exercise scenario synchronously for determinism.
        for item in generate(EPOCH):
            if item.release_at <= EPOCH + dt.timedelta(hours=1):
                r = c.post("/api/ingest/cdm", content=item.kvn.encode())
                assert r.status_code == 201, r.text
        yield c


def test_node_reports_identity_marking_and_clock(client):
    info = client.get("/api/node").json()
    assert info["marking"] == "UNCLASSIFIED // EXERCISE"
    assert info["clock"].startswith("fixed:")
    assert "conjunction" in info["modules"]


def test_active_events_are_sorted_by_time_to_maneuver_commit_point(client):
    events = client.get("/api/events").json()
    assert len(events) == 8
    ttm = [e["time_to_mcp_s"] for e in events]
    assert ttm == sorted(ttm)
    assert all(e["data_class"] == "EXERCISE" for e in events)


def test_every_pc_travels_with_its_method(client):
    for e in client.get("/api/events?scope=all").json():
        a = e["assessment"]
        assert a["method"] in {"FOSTER_ESTES_2D", "REFUSED"}
        if a["method"] == "REFUSED":
            assert a["pc"] is None and a["refusal_reason"]
            assert e["band"] == "UNASSESSED"


def test_nasa_library_events_are_real_and_in_the_past(client):
    past = client.get("/api/events?scope=past").json()
    assert len(past) == 53
    assert {e["data_class"] for e in past} == {"REAL"}


def test_dilution_headline_event_shows_worst_case_band(client):
    events = {e["secondary"]["id"]: e for e in client.get("/api/events").json()}
    dil = events["99412"]
    assert dil["cdm_count"] == 5
    assert dil["assessment"]["dilution_flag"] is True
    assert dil["band"] == "AMBER" and dil["worst_case_band"] == "RED"
    history = client.get(f"/api/events/{dil['event_id']}").json()["history"]
    pcs = [h["assessment"]["pc"] for h in history]
    peak = pcs.index(max(pcs))
    assert 0 < peak < len(pcs) - 1, "Pc rises then falls as the covariance inflates"
    assert history[-1]["assessment"]["pc"] < history[peak]["assessment"]["pc"]


def test_encounter_and_curve_use_the_engine_numbers(client):
    events = client.get("/api/events").json()
    red = next(e for e in events if e["secondary"]["id"] == "99118")
    enc = client.get(f"/api/events/{red['event_id']}/encounter").json()
    curve = client.get(f"/api/events/{red['event_id']}/dilution-curve").json()
    assert enc["available"] and enc["model_applies"]
    assert curve["pc_at_k1"] == pytest.approx(red["assessment"]["pc"], rel=1e-12)
    assert curve["k_star"] == pytest.approx(red["assessment"]["diagnostics"]["k_star"], rel=1e-6)
    assert len(curve["log10_k"]) == len(curve["pc"]) == 161


def test_refused_event_has_no_curve_but_still_has_geometry(client):
    events = client.get("/api/events").json()
    nocov = next(e for e in events if e["secondary"]["id"] == "99560")
    assert nocov["assessment"]["refusal_reason"] == "NO_COVARIANCE"
    assert client.get(f"/api/events/{nocov['event_id']}/dilution-curve").json() == {"available": False}
    traj = client.get(f"/api/events/{nocov['event_id']}/trajectory").json()
    assert len(traj["primary"]) == len(traj["secondary"]) == 81


@pytest.mark.parametrize("view", ["", "/encounter", "/dilution-curve", "/trajectory"])
def test_an_unknown_event_is_404_on_every_view_not_missing_data(client, view):
    """An event the node has never heard of is not an event without a
    covariance: a mistyped id must not read as "no covariance or HBR"."""
    r = client.get(f"/api/events/NO-SUCH-EVENT{view}")
    assert r.status_code == 404
    assert r.json()["detail"] == "no such event"


def test_a_known_event_without_the_data_still_says_so(client):
    nocov = next(e for e in client.get("/api/events").json() if e["secondary"]["id"] == "99560")
    encounter = client.get(f"/api/events/{nocov['event_id']}/encounter")
    curve = client.get(f"/api/events/{nocov['event_id']}/dilution-curve")
    assert (encounter.status_code, encounter.json()) == (200, {"available": False, "reason": "no covariance or HBR"})
    assert (curve.status_code, curve.json()) == (200, {"available": False})


def test_an_event_known_only_from_the_hubs_summary_has_no_geometry_yet(client):
    """On an edge, an event listed by the hub is known before its CDM arrives."""
    client.app.state.node.store.put_remote_summary("HUB-ONLY", {"e": "HUB-ONLY"}, "hub", EPOCH.isoformat())
    assert client.get("/api/events/HUB-ONLY/encounter").json() == {"available": False, "reason": "no covariance or HBR"}
    assert client.get("/api/events/HUB-ONLY/dilution-curve").json() == {"available": False}


def test_upload_is_idempotent_and_wrong_input_is_quarantined(client):
    raw = (CARA / "SampleCDMs" / "OmitronTestCase_Test01_HighPc.cdm").read_bytes()
    first = client.post("/api/ingest/cdm", content=raw)
    again = client.post("/api/ingest/cdm", content=raw)
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["status"] == "duplicate"

    bad = raw.replace(b"REF_FRAME                          = EME2000", b"REF_FRAME = ITRF", 1)
    r = client.post("/api/ingest/cdm", content=bad)
    assert r.status_code == 422
    assert r.json()["code"] == "UNSUPPORTED_REF_FRAME"
    assert client.get("/api/quarantine").json()[-1]["code"] == "UNSUPPORTED_REF_FRAME"


def test_read_only_node_refuses_ingest(tmp_path):
    app = create_app(Settings(exercise=False, library=False, read_only=True, web_dist=None, var_dir=str(tmp_path)))
    with TestClient(app) as c:
        assert c.post("/api/ingest/cdm", content=b"x").status_code == 403


def test_validation_tab_reproduces_the_tier3_result(client):
    v = client.get("/api/validation").json()
    assert v["available"]
    assert v["operational_count"] == 53
    assert v["worst_rel_error"] < 1e-6
    assert v["confusion"]["fn"] == 0


def test_console_is_served_under_a_same_origin_content_security_policy(client):
    """The browser, not just the code, forbids requests beyond this node."""
    csp = client.get("/api/health").headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "connect-src 'self'" in csp
    assert "'unsafe-eval'" not in csp.replace("'wasm-unsafe-eval'", "")
    assert "frame-ancestors 'none'" in csp


@pytest.mark.parametrize("page", ["/docs", "/docs/oauth2-redirect", "/redoc"])
def test_no_api_page_the_nodes_own_csp_would_blank(tmp_path, page):
    """FastAPI's Swagger UI and ReDoc pages load their scripts from a CDN
    and start them with an inline script. The node's CSP blocks both, so
    the pages rendered blank. They are not served; the schema they would
    have shown stays at /openapi.json (and in docs/icd/openapi.json)."""
    app = create_app(Settings(exercise=False, library=False, web_dist=None, var_dir=str(tmp_path)), start_background=False)
    with TestClient(app) as c:
        assert c.get(page).status_code == 404
        schema = c.get("/openapi.json")
    assert schema.status_code == 200
    assert "/api/health" in schema.json()["paths"]


def test_link_endpoint_logs_emulator_failure_instead_of_hiding_it(tmp_path, caplog):
    class BrokenEmulator:
        def status(self):
            raise ConnectionError("toxiproxy down")

    app = create_app(Settings(exercise=False, library=False, demo_controls=True, role="edge", web_dist=None, var_dir=str(tmp_path)))
    app.state.node.toxiproxy = BrokenEmulator()
    with TestClient(app) as c:
        body = c.get("/api/link").json()
    assert body["emulation"] is None
    record = next(r for r in caplog.records if r.getMessage() == "Link emulator unreachable")
    assert record.fields["error"] == "ConnectionError"
