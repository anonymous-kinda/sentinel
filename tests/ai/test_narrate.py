"""The template narrator: System Two when no language model may be used.

Deterministic prose over tool facts. It is held to the same grounding
guard as a model's answer - on every tool and every exercise event - so
the fallback is never less honest than the thing it replaces.
"""

import asyncio

import pytest

from sentinel.ai.grounding import check_grounding
from sentinel.ai.narrate import TemplateNarrator, format_pc


def narrate(tool: str, facts: dict) -> str:
    return asyncio.run(TemplateNarrator().narrate("", tool, facts))


def every_call(registry):
    yield "list_events", {}
    yield "list_events", {"band": "RED"}
    yield "list_events", {"band": "GREEN", "window_h": 1}
    yield "link_status", {}
    yield "sync_queue", {}
    for event in registry.execute("list_events", {})["events"]:
        yield "get_assessment", {"event_id": event["event_id"]}
        yield "explain_dilution", {"event_id": event["event_id"]}
        yield "draft_decision", {"event_id": event["event_id"], "decision": "MONITOR"}


def test_every_template_answer_passes_the_grounding_guard(registry):
    for tool, args in every_call(registry):
        facts = registry.execute(tool, args)
        text = narrate(tool, facts)
        result = check_grounding(text, facts)
        assert result.ok, (tool, args, result.unsupported, text)


def test_a_pc_is_never_stated_without_its_method(registry, event_of):
    text = narrate("get_assessment", registry.execute("get_assessment", {"event_id": event_of("99118")}))
    assert "Pc 5.0×10⁻³ (Foster-Estes 2D)" in text


def test_a_refusal_says_why_and_shows_the_gate(registry, event_of):
    text = narrate("get_assessment", registry.execute("get_assessment", {"event_id": event_of("99207")}))
    assert "No Pc" in text and "LOW_RELATIVE_VELOCITY" in text and "threshold 100" in text


def test_a_list_leads_with_the_count(registry):
    text = narrate("list_events", registry.execute("list_events", {"band": "RED"}))
    assert text.startswith("1 active event in band RED")
    assert "EX-DEB 118" in text


def test_an_empty_list_says_so_with_its_filters(registry):
    text = narrate("list_events", registry.execute("list_events", {"band": "GREEN", "window_h": 1}))
    assert text == "No active events in band GREEN with MCP within 1 h."


def test_dilution_is_explained_by_regime(registry, event_of):
    diluted = narrate("explain_dilution", registry.execute("explain_dilution", {"event_id": event_of("99412")}))
    assert "is diluted" in diluted and "better tracking could raise" in diluted
    robust = narrate("explain_dilution", registry.execute("explain_dilution", {"event_id": event_of("99118")}))
    assert "not diluted" in robust
    refused = narrate("explain_dilution", registry.execute("explain_dilution", {"event_id": event_of("99560")}))
    assert "does not apply" in refused and "NO_COVARIANCE" in refused


def test_a_draft_is_labelled_as_not_recorded(registry, event_of):
    facts = registry.execute("draft_decision", {"event_id": event_of("99118"), "decision": "MANEUVER"})
    text = narrate("draft_decision", facts)
    assert text.startswith("DRAFT: MANEUVER") and "not recorded until you confirm" in text


def test_a_past_commit_point_reads_as_past():
    facts = {"count": 1, "filters": {"band": None, "window_h": None}, "events": [
        {"event_id": "a-b-c", "primary": "SAT", "secondary": "DEB", "secondary_id": "9", "band": "GREEN",
         "method": "FOSTER_ESTES_2D", "pc": 2.1e-9, "refusal_reason": None, "time_to_mcp_h": -3.2,
         "data_class": "EXERCISE", "verification": "LOCAL"}]}
    text = narrate("list_events", facts)
    assert "MCP passed 3.2 h ago" in text and check_grounding(text, facts).ok


@pytest.mark.parametrize(
    "pc,text",
    [(0.005023021865686615, "5.0×10⁻³"), (3.6222e-05, "3.6×10⁻⁵"), (2.0656e-15, "2.1×10⁻¹⁵"), (0.0, "0"), (0.53, "5.3×10⁻¹")],
)
def test_pc_reads_as_it_does_on_the_console(pc, text):
    assert format_pc(pc) == text
