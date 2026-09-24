"""Scoring a router against labelled requests.

A call is right when both the tool and its arguments match the label. An
out-of-scope request is handled right when the assistant would not act -
the router abstained, or was too unsure to pass the confidence gate.
"""

import pytest

from sentinel.ai.evaluation import Case, score, summarize
from sentinel.ai.router import Route, RoutingContext

E118, E412 = "99001-99118-20260924T070000", "99001-99412-20260924T180000"
CONTEXT = RoutingContext([{"event_id": E118, "label": "118"}, {"event_id": E412, "label": "412"}])
DRAFT = Case("c1", "draft a maneuver for 118", "draft_decision", event="99118", decision="MANEUVER")
LIST = Case("c2", "anything red?", "list_events", band="RED")
SANDWICH = Case("x1", "make me a sandwich", None)


def route(tool, args, confidence):
    return Route(tool, args, confidence, "test")


def test_a_right_call_matches_tool_and_arguments():
    o = score(DRAFT, route("draft_decision", {"event_id": E118, "decision": "MANEUVER"}, 0.9), CONTEXT)
    assert o.tool_correct and o.call_correct and o.acted


def test_the_right_tool_on_the_wrong_event_is_a_wrong_call():
    o = score(DRAFT, route("draft_decision", {"event_id": E412, "decision": "MANEUVER"}, 0.9), CONTEXT)
    assert o.tool_correct and not o.call_correct


def test_a_missing_filter_is_a_wrong_call():
    assert not score(LIST, route("list_events", {}, 0.9), CONTEXT).call_correct
    assert score(LIST, route("list_events", {"band": "RED"}, 0.9), CONTEXT).call_correct


def test_an_unsure_router_does_not_act():
    o = score(LIST, route("list_events", {"band": "RED"}, 0.4), CONTEXT)
    assert o.tool_correct and not o.acted


def test_an_event_tool_without_an_event_does_not_act():
    assert not score(DRAFT, route("draft_decision", {"decision": "MANEUVER"}, 0.9), CONTEXT).acted


def test_out_of_scope_is_right_only_when_the_assistant_would_not_act():
    assert score(SANDWICH, route(None, {}, 0.0), CONTEXT).call_correct
    assert score(SANDWICH, route("list_events", {}, 0.3), CONTEXT).call_correct
    assert not score(SANDWICH, route("list_events", {}, 0.7), CONTEXT).call_correct


def test_the_summary_separates_routing_accuracy_coverage_and_calibration():
    cases = [DRAFT, LIST, Case("c3", "is 412 diluted?", "explain_dilution", event="99412"), SANDWICH]
    outcomes = [
        score(DRAFT, route("draft_decision", {"event_id": E118, "decision": "MANEUVER"}, 0.9), CONTEXT),
        score(LIST, route("sync_queue", {}, 0.8), CONTEXT),
        score(cases[2], route("explain_dilution", {"event_id": E412}, 0.4), CONTEXT),
        score(SANDWICH, route("list_events", {}, 0.3), CONTEXT),
    ]
    s = summarize(cases, outcomes)
    assert (s["cases"], s["in_scope"], s["out_of_scope"]) == (4, 3, 1)
    assert s["tool_accuracy"] == pytest.approx(2 / 3) and s["call_accuracy"] == pytest.approx(2 / 3)
    assert s["coverage"] == pytest.approx(2 / 3), "acted on c1 and c2; asked back on c3"
    assert s["selective_accuracy"] == pytest.approx(1 / 2), "of the calls it acted on, one was right"
    assert s["abstention"] == 1.0
    # (0.9,✓) (0.8,✗) (0.4,✓) (0.3,✗): (0.01 + 0.64 + 0.36 + 0.09) / 4
    assert s["brier"] == pytest.approx(0.275)
