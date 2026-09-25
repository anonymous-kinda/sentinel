"""A decision made on the hub's summary, before the CDM arrives.

On a thin link an edge operator may have to decide from a HUB-ASSERTED
summary (SUMMARY-ONLY is a designed state). The decision must still record
what it was made against, so that when the edge later receives a newer
CDM the decision is flagged REVIEW REQUIRED, as it is for a decision made
against a local CDM.
"""

from sentinel.ai.tools import ToolRegistry
from sentinel.conjunction.exercise import generate

from .conftest import EPOCH, run


def _dilution_event(edge):
    return next(e for e in edge.conj.list_events("active") if e["secondary"]["id"] == "99412")


def _decide_on_the_summary(hub, edge, agent):
    agent.apply_manifest(run(agent.fetch_manifest()))           # summaries only, no CDM yet
    event = _dilution_event(edge)
    assert event["verification"] == "HUB_ASSERTED"
    run(edge.ops.append(event["event_id"], "DECISION", {"decision": "MONITOR"}, "maj.ortiz@alpha"))
    return event["event_id"]


def test_a_decision_on_a_summary_records_what_the_hub_asserted(pair):
    hub, edge, agent, _ = pair
    event_id = _decide_on_the_summary(hub, edge, agent)
    [entry] = edge.ops.entries(event_id)
    assert entry["event_ref"].get("cdm_sha256"), "the decision names no record at all"


def test_it_is_flagged_for_review_when_a_newer_cdm_arrives(pair):
    hub, edge, agent, clock = pair
    event_id = _decide_on_the_summary(hub, edge, agent)
    clock.advance(3600)                                          # the scenario's later updates are released
    for item in generate(EPOCH):
        if item.release_at <= clock.now():
            run(hub.conj.ingest(item.kvn.encode(), "exercise", "EXERCISE"))
    run(agent.cycle())
    assert edge.ops.entries(event_id)[-1]["review_required"] is True


def test_it_is_not_flagged_when_the_cdm_that_arrives_is_the_one_it_was_made_on(pair):
    hub, edge, agent, _ = pair
    event_id = _decide_on_the_summary(hub, edge, agent)
    run(agent.cycle())
    assert _dilution_event(edge)["verification"] == "VERIFIED"
    assert edge.ops.entries(event_id)[-1]["review_required"] is False


def test_an_ai_draft_on_the_summary_is_confirmed_against_the_same_cdm_once_it_arrives(pair):
    hub, edge, agent, _ = pair
    agent.apply_manifest(run(agent.fetch_manifest()))
    event_id = _dilution_event(edge)["event_id"]
    tools = ToolRegistry(edge.conj, edge.ops, agent.link, sync_status=agent.status)
    draft = tools.execute("draft_decision", {"event_id": event_id, "decision": "MONITOR"})
    run(agent.cycle())                                           # the CDM the summary named arrives
    entry = run(tools.record_decision(draft, "maj.ortiz@alpha", "", {"router": "deterministic"}))
    assert entry["event_ref"]["cdm_sha256"] == draft["against"]["cdm_sha256"]
    assert entry["review_required"] is False
