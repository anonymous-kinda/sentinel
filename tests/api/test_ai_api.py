"""The assistant over HTTP: status, ask, confirm, audit.

No hosted service is reachable in tests (pytest-socket), so these run the
local tier end to end; provider selection is checked through /status.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.api.settings import Settings
from sentinel.clock import FixedClock
from sentinel.conjunction.exercise import generate

EPOCH = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.UTC)
NOW = EPOCH + dt.timedelta(hours=1)
OP1, OP2 = {"X-Sentinel-Operator": "op1"}, {"X-Sentinel-Operator": "op2"}


def node(tmp_path, **overrides):
    settings = Settings(exercise=False, library=False, web_dist=None, var_dir=str(tmp_path), **overrides)
    client = TestClient(create_app(settings, clock=FixedClock(NOW), start_background=False))
    client.__enter__()
    for item in generate(EPOCH):
        if item.release_at <= NOW:
            client.post("/api/ingest/cdm", content=item.kvn.encode())
    return client


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = node(tmp_path)
    yield c
    c.__exit__(None, None, None)


def test_status_reports_the_tier_and_why(client):
    s = client.get("/api/ai/status").json()
    assert s["enabled"] is True and s["cloud_opt_in"] is False
    assert s["providers"] == {"jev": False, "claude": False}
    assert s["tier"]["router"] == "deterministic" and s["tier"]["narrator"] == "template"
    assert s["tier"]["reason"] == "Hosted AI not approved on this node"
    assert s["link_source"] == "assumed: no upstream link on a standalone node"


def test_the_node_reports_the_assistant_module(client):
    assert "ai" in client.get("/api/node").json()["modules"]


def test_ask_answers_from_the_tools(client):
    a = client.post("/api/ai/ask", json={"text": "/events red"}, headers=OP1).json()
    assert a["status"] == "answered" and a["text"].startswith("1 active event in band RED")
    assert a["grounding"]["ok"] and a["route"]["provider"] == "deterministic"


def test_a_draft_is_recorded_only_on_confirm_and_only_once(client):
    a = client.post("/api/ai/ask", json={"text": "/draft 118 monitor"}, headers=OP1).json()
    event_id = a["facts"]["event_id"]
    assert a["status"] == "draft"
    assert client.get(f"/api/events/{event_id}/ops").json()["entries"] == []

    r = client.post("/api/ai/confirm", json={"draft_id": a["draft_id"], "rationale": "watch next update"}, headers=OP2)
    assert r.status_code == 201
    assert r.json()["body"]["drafted_by"]["router"] == "deterministic"
    [entry] = client.get(f"/api/events/{event_id}/ops").json()["entries"]
    assert entry["kind"] == "DECISION" and entry["author"] == "op2" and entry["body"]["decision"] == "MONITOR"

    assert client.post("/api/ai/confirm", json={"draft_id": a["draft_id"]}, headers=OP2).status_code == 404


def test_the_audit_chain_is_served_persisted_and_verifies(client, tmp_path):
    client.post("/api/ai/ask", json={"text": "/link"}, headers=OP1)
    audit = client.get("/api/ai/audit").json()
    assert audit[-1]["question"] == "/link" and audit[-1]["author"] == "op1"
    assert client.get("/api/ai/audit/verify").json() == {"ok": True, "count": len(audit), "first_bad": None}
    assert (tmp_path / "ai-audit.jsonl").read_text().count("\n") == len(audit)


def test_a_torn_audit_line_breaks_the_chain_not_the_node(tmp_path, caplog):
    """A power cut mid-write leaves a line with no end. The node still starts,
    the assistant still answers and records, and the chain reports the break."""
    (tmp_path / "ai-audit.jsonl").write_bytes(b'{"at":"2026-09-23T12:00:00+00:00","author":"op1","kind":"a')
    c = node(tmp_path)
    try:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/ai/audit/verify").json() == {"ok": False, "count": 1, "first_bad": 0}
        assert c.post("/api/ai/ask", json={"text": "/link"}, headers=OP1).json()["status"] == "answered"
        assert [e["question"] for e in c.get("/api/ai/audit").json()] == ["/link"]
        assert c.get("/api/ai/audit/verify").json() == {"ok": False, "count": 2, "first_bad": 0}
    finally:
        c.__exit__(None, None, None)
    assert any(r.getMessage() == "Audit chain broken" for r in caplog.records)


def test_an_audit_line_edited_while_the_node_runs_is_found(client, tmp_path):
    for text in ("/link", "/events", "/queue"):
        client.post("/api/ai/ask", json={"text": text}, headers=OP1)
    path = tmp_path / "ai-audit.jsonl"
    path.write_text(path.read_text().replace('"/events"', '"/events red"'))
    assert client.get("/api/ai/audit/verify").json() == {"ok": False, "count": 3, "first_bad": 1}


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "x" * 2001}, {}])
def test_empty_or_oversized_questions_are_rejected(client, body):
    assert client.post("/api/ai/ask", json=body).status_code == 422


def test_the_assistant_can_be_switched_off(tmp_path):
    c = node(tmp_path, ai=False)
    assert c.get("/api/ai/status").json() == {"enabled": False}
    assert "ai" not in c.get("/api/node").json()["modules"]
    assert c.post("/api/ai/ask", json={"text": "/events"}).status_code == 404


def test_a_read_only_node_answers_but_never_records(tmp_path):
    c = node(tmp_path, read_only=True)
    a = c.post("/api/ai/ask", json={"text": "/events"}).json()
    assert a["status"] == "answered"
    assert c.post("/api/ai/confirm", json={"draft_id": "anything"}).status_code == 403


def test_a_read_only_node_offers_no_draft_it_could_never_confirm(tmp_path):
    c = node(tmp_path, read_only=True)
    a = c.post("/api/ai/ask", json={"text": "/draft 118 monitor"}).json()
    assert a["status"] == "clarify" and a["draft_id"] is None
    assert "read-only" in a["text"]


def test_confirming_an_evicted_draft_is_404_unknown_draft(client):
    client.app.state.node.extensions["ai"].max_drafts = 1
    first, second = (client.post("/api/ai/ask", json={"text": "/draft 118 monitor"}, headers=OP1).json() for _ in range(2))
    r = client.post("/api/ai/confirm", json={"draft_id": first["draft_id"]}, headers=OP2)
    assert r.status_code == 404 and r.json()["detail"] == "unknown_draft"
    assert client.post("/api/ai/confirm", json={"draft_id": second["draft_id"]}, headers=OP2).status_code == 201


def test_hosted_providers_are_used_only_with_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    opted_out = node(tmp_path / "a").get("/api/ai/status").json()
    assert opted_out["providers"] == {"jev": True, "claude": True}
    assert opted_out["tier"]["router"] == "deterministic"

    opted_in = node(tmp_path / "b", ai_cloud=True).get("/api/ai/status").json()
    assert opted_in["tier"]["router"] == "jev" and opted_in["tier"]["narrator"] == "claude"
    assert opted_in["models"] == {"jev": "jev-1.13.0", "claude": "claude-opus-5"}
