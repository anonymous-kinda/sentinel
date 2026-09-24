"""The local router: works with no network, no model, no key.

Slash commands are exact (confidence 1.0). Plain-language requests match
simple keyword rules (confidence 0.6). Anything else is not guessed at:
tool None, confidence 0, and the operator is asked.
"""

import asyncio

import pytest

from sentinel.ai.router import DeterministicRouter, RoutingContext

EVENTS = [
    {"event_id": "99001-99118-20260924T205723", "label": "EXSAT-1 x EX-DEB 118, RED, MCP in 10.9 h"},
    {"event_id": "99001-99412-20260925T075723", "label": "EXSAT-1 x EX-DEB 412, AMBER (diluted, worst RED), MCP in 21.9 h"},
    {"event_id": "99007-99207-20260926T055723", "label": "EXGEO-7 x EX-DEB 207, no Pc (low relative velocity)"},
]
CTX = RoutingContext(events=EVENTS)


def route(text):
    return asyncio.run(DeterministicRouter().route(text, CTX))


@pytest.mark.parametrize(
    "text,tool,args",
    [
        ("/events red 48h", "list_events", {"band": "RED", "window_h": 48}),
        ("/events", "list_events", {}),
        ("/assess 2", "get_assessment", {"event_id": EVENTS[1]["event_id"]}),
        ("/explain 99118", "explain_dilution", {"event_id": EVENTS[0]["event_id"]}),
        ("/link", "link_status", {}),
        ("/queue", "sync_queue", {}),
        ("/draft 1 maneuver", "draft_decision", {"event_id": EVENTS[0]["event_id"], "decision": "MANEUVER"}),
    ],
)
def test_slash_commands_are_exact(text, tool, args):
    r = route(text)
    assert (r.tool, r.args, r.confidence) == (tool, args, 1.0)
    assert r.provider == "deterministic"


@pytest.mark.parametrize(
    "text,tool,args",
    [
        ("is the DEB 412 event diluted?", "explain_dilution", {"event_id": EVENTS[1]["event_id"]}),
        ("which events need action in the next 24 hours", "list_events", {"window_h": 24}),
        ("show me the red ones", "list_events", {"band": "RED"}),
        ("how is the link to the hub doing", "link_status", {}),
        ("what's still waiting to sync", "sync_queue", {}),
        ("draft a no maneuver decision for 207", "draft_decision", {"event_id": EVENTS[2]["event_id"], "decision": "NO_MANEUVER"}),
        ("what is the risk on EX-DEB 118", "get_assessment", {"event_id": EVENTS[0]["event_id"]}),
    ],
)
def test_plain_language_keyword_rules(text, tool, args):
    r = route(text)
    assert (r.tool, r.args) == (tool, args)
    assert r.confidence == 0.6


def test_unrecognised_requests_are_not_guessed():
    r = route("tell me a joke about orbital mechanics")
    assert r.tool is None and r.confidence == 0.0


def test_event_reference_that_matches_nothing_is_left_empty():
    r = route("/assess 99999")
    assert r.tool == "get_assessment" and "event_id" not in r.args


def test_a_routing_context_names_each_event_by_objects_band_and_time_to_act():
    facts = [{"event_id": "99001-99118-20260924T070000", "primary": "EXSAT-1 (EXERCISE)",
              "secondary": "EX-DEB 118 (EXERCISE)", "band": "RED", "time_to_mcp_h": 10.0}]
    context = RoutingContext.from_facts(facts)
    assert context.events == [{"event_id": "99001-99118-20260924T070000",
                               "label": "EXSAT-1 (EXERCISE) vs EX-DEB 118 (EXERCISE), RED, MCP in 10.0 h"}]
