"""The assistant's tools: deterministic code over the node's own services.

Each tool returns plain facts - the evidence an answer may cite. A tool
that would write returns a draft instead; nothing is recorded until a
person confirms it.
"""

import re

import pytest

from sentinel.ai.catalog import TOOLS
from sentinel.ai.tools import ToolError


def test_list_events_is_sorted_by_commit_point_and_filterable(registry, event_of):
    everything = registry.execute("list_events", {})
    hours = [e["time_to_mcp_h"] for e in everything["events"]]
    assert hours == sorted(hours) and everything["count"] == len(hours) == 8
    red = registry.execute("list_events", {"band": "RED"})
    assert red["count"] >= 1 and {e["band"] for e in red["events"]} == {"RED"}
    soon = registry.execute("list_events", {"window_h": 12})
    assert all(e["time_to_mcp_h"] <= 12 for e in soon["events"])
    refused = next(e for e in everything["events"] if e["secondary_id"] == "99560")
    assert refused["refusal_reason"] == "NO_COVARIANCE", "a list says why an event has no Pc"


def test_assessment_carries_method_and_never_a_bare_probability(registry, event_of):
    result = registry.execute("get_assessment", {"event_id": event_of("99118")})
    assert result["method"] == "FOSTER_ESTES_2D" and result["pc"] > 0
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}Z", result["tca_utc"]), "dates are formatted by code"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}Z", result["mcp_utc"])
    refused = registry.execute("get_assessment", {"event_id": event_of("99560")})
    assert refused["method"] == "REFUSED" and refused["pc"] is None and refused["refusal_reason"] == "NO_COVARIANCE"
    gated = registry.execute("get_assessment", {"event_id": event_of("99207")})
    assert gated["refusal_detail"]["threshold"] == 100.0, "a refusal carries the value that tripped the gate"
    assert "independence_assumed" not in gated["refusal_detail"]


def test_explain_dilution_is_deterministic_facts(registry, event_of):
    diluted = registry.execute("explain_dilution", {"event_id": event_of("99412")})
    assert diluted["diluted"] is True and diluted["k_star"] < 1 and diluted["pc_max"] >= diluted["pc"]
    refused = registry.execute("explain_dilution", {"event_id": event_of("99560")})
    assert refused["applies"] is False and refused["refusal_reason"] == "NO_COVARIANCE"


def test_link_and_queue_report_node_state(registry, event_of):
    assert registry.execute("link_status", {})["state"] in {"CONNECTED", "DEGRADED", "LIMITED"}
    assert registry.execute("sync_queue", {})["queue"][0]["class"] == "P1_URGENT"


def test_draft_decision_writes_nothing(registry, event_of):
    event_id = event_of("99118")
    before = len(registry.ops.entries(event_id))
    draft = registry.execute("draft_decision", {"event_id": event_id, "decision": "MANEUVER"})
    assert draft["draft"] is True and draft["decision"] == "MANEUVER"
    assert draft["against"]["message_id"]
    assert len(registry.ops.entries(event_id)) == before


@pytest.mark.parametrize(
    "tool,args,code",
    [
        ("get_assessment", {}, "missing_event"),
        ("get_assessment", {"event_id": "nope"}, "unknown_event"),
        ("draft_decision", {"event_id": "nope", "decision": "MANEUVER"}, "unknown_event"),
        ("no_such_tool", {}, "unknown_tool"),
    ],
)
def test_bad_calls_fail_with_a_named_reason(registry, tool, args, code):
    with pytest.raises(ToolError) as exc:
        registry.execute(tool, args)
    assert exc.value.code == code


def test_draft_needs_a_decision(registry, event_of):
    with pytest.raises(ToolError) as exc:
        registry.execute("draft_decision", {"event_id": event_of("99118")})
    assert exc.value.code == "missing_decision"


def test_draft_rejects_a_decision_outside_the_catalog(registry, event_of):
    with pytest.raises(ToolError) as exc:
        registry.execute("draft_decision", {"event_id": event_of("99118"), "decision": "LAUNCH"})
    assert exc.value.code == "invalid_decision"


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_every_catalogued_tool_is_served(registry, event_of, tool):
    args = {"event_id": event_of("99118"), "decision": "MONITOR"} if TOOLS[tool].needs_event else {}
    assert isinstance(registry.execute(tool, args), dict)


@pytest.mark.parametrize("tool", ["explain_dilution", "draft_decision"])
def test_event_tools_name_the_objects(registry, event_of, tool):
    facts = registry.execute(tool, {"event_id": event_of("99118"), "decision": "MONITOR"})
    assert facts["secondary"].startswith("EX-DEB 118") and facts["primary"]
