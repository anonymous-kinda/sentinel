"""Edges of the assistant's guards that a hosted model can reach.

A router's answer and a narrator's prose come from outside the node. The
confidence gate, the catalog and the grounding guard are what stand
between them and an operator, so each must fail closed on input that is
malformed rather than merely wrong.
"""

import asyncio
import json
import math

import httpx2
import pytest
from typesafe_sdk import AsyncTypeSafeClient

from sentinel.ai.assistant import gate
from sentinel.ai.grounding import check_grounding
from sentinel.ai.router import Route, RouterUnavailable, RoutingContext
from sentinel.ai.router_jev import NO_RETRY, JevRouter
from sentinel.audit import AuditLog

from .test_assistant import ScriptedRouter, ask, jev_route, make
from .test_router_jev import CTX, EVENTS, answer

FACTS = {"event_id": EVENTS[0]["event_id"], "pc": 0.006271, "miss_distance_m": 200.3, "time_to_mcp_h": 10.9,
         "count": 0}


# ------------------------------------------------------- confidence gate
@pytest.mark.parametrize("confidence", [math.nan, math.inf, -0.1, 1.5])
def test_a_confidence_that_is_not_a_probability_never_passes_the_gate(confidence):
    route = Route("draft_decision", {"event_id": "E", "decision": "MANEUVER"}, confidence, "jev")
    assert gate(route) == "unsure"


def test_a_nan_confidence_from_the_router_asks_back_instead_of_drafting(registry, event_of):
    route = jev_route("draft_decision", {"event_id": event_of("99118"), "decision": "MANEUVER"}, math.nan)
    a = ask(make(registry, jev=ScriptedRouter(route)), "maneuver on 118")
    assert a.status == "clarify" and a.draft_id is None


# ------------------------------------------------------- the router's answer
def _router(body) -> JevRouter:
    def handler(request):
        return httpx2.Response(200, json=body, headers={"x-typesafe-request-id": "req_1"})

    return JevRouter(AsyncTypeSafeClient(api_key="k", transport=httpx2.MockTransport(handler), retry=NO_RETRY))


def _without(body: dict, question: str) -> dict:
    return {**body, "answers": {k: v for k, v in body["answers"].items() if k != question}}


@pytest.mark.parametrize("body,reason", [
    (answer(tool="delete_everything"), "malformed"),
    (answer(band="PURPLE", tool="list_events"), "malformed"),
    (answer(event="99999-99999-20260101T000000"), "malformed"),
    (_without(answer(), "event"), "malformed"),
    ({**answer(), "answers": {**answer()["answers"], "tool": {"type": "choice", "choice": "list_events"}}}, "error"),
], ids=["tool-outside-the-catalog", "band-outside-the-catalog", "event-not-on-this-node", "missing-question",
        "missing-confidence (the SDK rejects it)"])
def test_a_malformed_router_answer_is_unavailable_not_a_crash(body, reason):
    with pytest.raises(RouterUnavailable) as excinfo:
        asyncio.run(_router(body).route("anything", CTX))
    assert excinfo.value.reason == reason


def test_a_malformed_router_answer_falls_back_to_the_local_router(registry):
    a = ask(make(registry, jev=_router(answer(tool="delete_everything"))), "/link")
    assert a.status == "answered" and a.route["provider"] == "deterministic"
    assert a.fallbacks == [{"from": "jev", "to": "deterministic", "reason": "malformed"}]


# ------------------------------------------------------- grounding guard
@pytest.mark.parametrize("text", [
    "The collision probability is .9",
    "Miss distance ,5 km.",
    "Pc 0,9",
])
def test_every_digit_in_an_answer_is_checked(text):
    """A number written with a leading decimal point, or after a comma, was
    not extracted at all: the guard passed it unchecked."""
    assert not check_grounding(text, FACTS).ok


def test_digits_inside_a_grounded_identifier_are_still_accepted():
    assert check_grounding(f"Event {FACTS['event_id']}: Pc 6.3×10⁻³, miss 200 m.", FACTS).ok


# ------------------------------------------------------------- the audit
def test_no_api_key_reaches_the_audit_record(registry, tmp_path, monkeypatch):
    """Keys live in the environment and the SDK clients; the audit records
    reasons, never the request."""
    secret = "sk-test-DO-NOT-LOG-5f1c"
    monkeypatch.setenv("TYPESAFE_API_KEY", secret)
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)

    def refuse(request):
        return httpx2.Response(401, json={"error": {"message": f"bad key {request.headers.get('authorization')}"}})

    jev = JevRouter(AsyncTypeSafeClient(api_key=secret, transport=httpx2.MockTransport(refuse), retry=NO_RETRY))
    audit = AuditLog(tmp_path / "ai-audit.jsonl")
    assistant = make(registry, jev=jev, audit=audit)
    for question in ("/link", "what is the risk on 118?", "/draft 118 monitor"):
        ask(assistant, question)
    written = (tmp_path / "ai-audit.jsonl").read_text()
    assert secret not in written
    assert all(json.loads(line)["fallbacks"] for line in written.splitlines())


def test_the_routing_context_names_only_this_nodes_events():
    assert {e["event_id"] for e in RoutingContext(EVENTS).events} == {e["event_id"] for e in EVENTS}
