"""Jev (TypeSafe System One) as the routing layer.

The real TypeSafe SDK runs against an injected mock transport, so these
tests pin the exact wire request Sentinel sends and how it reads the
answer - with no network and no API key. Response shapes follow the
published API reference (docs.typesafe.ai/api).
"""

import asyncio
import json

import httpx2
import pytest
from typesafe_sdk import AsyncTypeSafeClient

from sentinel.ai.catalog import DECISIONS, TOOLS
from sentinel.ai.router import RoutingContext
from sentinel.ai.router_jev import JEV_MODEL, NO_RETRY, JevRouter, RouterUnavailable

EVENTS = [
    {"event_id": "99001-99118-20260924T205723", "label": "EXSAT-1 x EX-DEB 118, RED, MCP in 10.9 h"},
    {"event_id": "99001-99412-20260925T075723", "label": "EXSAT-1 x EX-DEB 412, AMBER (diluted), MCP in 21.9 h"},
]
CTX = RoutingContext(events=EVENTS)


def answer(tool="explain_dilution", tool_p=0.86, event=EVENTS[1]["event_id"], band="any", decision="none"):
    tools = {name: (tool_p if name == tool else (1 - tool_p) / (len(TOOLS) - 1)) for name in TOOLS}
    return {
        "model": "jev-1.13.0",
        "answers": {
            "tool": {"type": "choice", "choice": tool, "confidence": 0.8, "probabilities": tools},
            "event": {"type": "choice", "choice": event, "confidence": 0.9,
                      "probabilities": {event: 0.93, "none": 0.07}},
            "band": {"type": "choice", "choice": band, "confidence": 0.95, "probabilities": {band: 1.0}},
            "decision": {"type": "choice", "choice": decision, "confidence": 0.9, "probabilities": {decision: 1.0}},
            "consequential": {"type": "noul", "noul": 0.04},
        },
        "usage": {"input_tokens": 612, "output_tokens": 71},
    }


def router_with(status=200, body=None, sink=None):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if sink is not None:
            sink["request"] = request
        return httpx2.Response(status, json=body if body is not None else answer(), headers={"x-typesafe-request-id": "req_1"})

    client = AsyncTypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(handler), retry=NO_RETRY)
    return JevRouter(client)


def run(router, text="is the 412 event's collision probability diluted?"):
    return asyncio.run(router.route(text, CTX))


def test_request_asks_parallel_typed_questions_over_the_catalog_and_known_events():
    sink = {}
    run(router_with(sink=sink))
    req = sink["request"]
    body = json.loads(req.content)
    assert req.url.path == "/v1/systemone"
    assert req.headers["authorization"] == "Bearer test-key"
    assert body["model"] == JEV_MODEL == "jev-1.13.0", "pinned: thresholds are tuned to one model version"
    assert body["state"]["operator_request"].startswith("is the 412 event")
    q = body["questions"]
    assert q["tool"]["type"] == "choice" and set(q["tool"]["criteria"]) == set(TOOLS)
    assert set(q["event"]["criteria"]) == {e["event_id"] for e in EVENTS} | {"none"}
    assert set(q["decision"]["criteria"]) == set(DECISIONS) | {"none"}
    assert q["consequential"]["type"] == "noul"


def test_answer_becomes_a_route_with_calibrated_probabilities():
    r = run(router_with())
    assert r.provider == "jev"
    assert r.tool == "explain_dilution"
    assert r.args == {"event_id": EVENTS[1]["event_id"]}
    assert r.confidence == pytest.approx(0.8)
    assert r.tool_probabilities["explain_dilution"] == pytest.approx(0.86)
    assert r.event_probabilities[EVENTS[1]["event_id"]] == pytest.approx(0.93)
    assert r.detail["model"] == "jev-1.13.0"
    assert r.detail["request_bytes"] > 0 and r.detail["response_bytes"] > 0
    assert r.detail["request_id"] == "req_1"


def test_list_filters_come_from_jev_band_and_a_parsed_window():
    body = answer(tool="list_events", event="none", band="RED")
    r = run(router_with(body=body), "anything red due in the next 36 hours?")
    assert r.args == {"band": "RED", "window_h": 36}, "Jev is not a calculator: numbers are parsed, not asked"


def test_draft_carries_the_decision_and_no_event_when_jev_says_none():
    body = answer(tool="draft_decision", event="none", decision="MONITOR")
    r = run(router_with(body=body), "draft a monitor decision")
    assert r.args == {"decision": "MONITOR"}


@pytest.mark.parametrize("status,reason", [(401, "authentication"), (429, "rate_limited"), (500, "server_error")])
def test_service_failures_raise_router_unavailable(status, reason):
    with pytest.raises(RouterUnavailable) as exc:
        run(router_with(status=status, body={"error": {"message": "x"}}))
    assert exc.value.reason == reason


def test_production_client_fails_fast_so_the_local_router_can_take_over(monkeypatch):
    """One attempt, no backoff: on a degraded link, waiting out retries is
    worse than answering locally. (retry=None means *default* retries.)"""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(503, json={"error": {"message": "overloaded"}})

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    router = JevRouter.from_env(transport=httpx2.MockTransport(handler))
    with pytest.raises(RouterUnavailable):
        run(router)
    assert len(calls) == 1
