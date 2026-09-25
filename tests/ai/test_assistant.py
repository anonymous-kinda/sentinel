"""The assistant: route, gate, act, narrate, check, audit.

Hosted services are replaced by scripted stand-ins so each rule can be
driven directly: which tier is allowed, what happens when a service is
down, when the assistant must ask instead of act, when an AI answer is
withheld, and that nothing is written until a person confirms.
"""

import asyncio

import pytest

from sentinel.ai.assistant import MAX_DRAFTS, TOOL_QUESTIONS, Assistant
from sentinel.ai.narrate import NarratorUnavailable
from sentinel.ai.router import Route, RouterUnavailable
from sentinel.ai.tools import ToolError
from sentinel.audit import AuditLog
from sentinel.clock import FixedClock
from sentinel.conjunction.exercise import generate

from .conftest import EPOCH, NOW, build_registry


class ScriptedRouter:
    name = "jev"

    def __init__(self, route: Route | None = None, error: str | None = None):
        self._route, self._error, self.calls = route, error, 0

    async def route(self, text, context):
        self.calls += 1
        if self._error:
            raise RouterUnavailable(self._error)
        return self._route


class ScriptedNarrator:
    name = "claude"

    def __init__(self, text: str = "", error: str | None = None):
        self._text, self._error, self.calls = text, error, 0

    async def narrate(self, question, tool, facts):
        self.calls += 1
        if self._error:
            raise NarratorUnavailable(self._error)
        return self._text


def make(registry, link="CONNECTED", marking="UNCLASSIFIED//EXERCISE", jev=None, llm=None, audit=None, **options):
    return Assistant(
        registry,
        link_state=lambda: link,
        marking=marking,
        cloud_opt_in=True,
        audit=audit or AuditLog(None),
        clock=FixedClock(NOW),
        jev=jev,
        llm=llm,
        **options,
    )


def ask(assistant, text):
    return asyncio.run(assistant.ask(text, author="op1"))


def jev_route(tool, args, confidence, tools=None, events=None):
    return Route(tool, args, confidence, "jev", tools or {tool: confidence}, events or {}, {"model": "jev-1.13.0"})


# ------------------------------------------------------------------ tiers
def test_connected_and_unclassified_routes_with_jev(registry, event_of):
    jev = ScriptedRouter(jev_route("get_assessment", {"event_id": event_of("99118")}, 0.91))
    a = ask(make(registry, jev=jev), "how risky is the 118 conjunction?")
    assert jev.calls == 1 and a.tier["router"] == "jev" and a.route["provider"] == "jev"
    assert a.status == "answered" and "Pc 5.0×10⁻³ (Foster-Estes 2D)" in a.text
    assert a.grounding["ok"]


@pytest.mark.parametrize(
    "link,marking",
    [("DENIED", "UNCLASSIFIED//EXERCISE"), ("CONNECTED", "SECRET//EXERCISE"), ("CONNECTED", "UNCLASSIFIED//CUI")],
)
def test_denied_or_classified_never_calls_a_hosted_service(registry, link, marking):
    jev, llm = ScriptedRouter(jev_route("list_events", {}, 0.9)), ScriptedNarrator("8 events.")
    a = ask(make(registry, link=link, marking=marking, jev=jev, llm=llm), "/events red")
    assert jev.calls == 0 and llm.calls == 0
    assert a.status == "answered" and a.route["provider"] == "deterministic" and a.narrated_by == "template"


def test_a_jev_outage_falls_back_to_the_local_router(registry):
    a = ask(make(registry, jev=ScriptedRouter(error="unreachable")), "/link")
    assert a.status == "answered" and a.route["provider"] == "deterministic"
    assert a.fallbacks == [{"from": "jev", "to": "deterministic", "reason": "unreachable"}]


# ------------------------------------------------------------------ gates
def test_low_confidence_asks_instead_of_acting(registry):
    probabilities = {"list_events": 0.38, "sync_queue": 0.33, "link_status": 0.2, "get_assessment": 0.09}
    a = ask(make(registry, jev=ScriptedRouter(jev_route("list_events", {}, 0.38, probabilities))), "what's going on")
    assert a.status == "clarify" and a.facts is None
    assert [alt["tool"] for alt in a.alternatives] == ["list_events", "sync_queue"]


def test_an_unmatched_request_gets_the_commands(registry):
    a = ask(make(registry, link="DENIED"), "make me a sandwich")
    assert a.status == "clarify" and "/events" in a.text and a.alternatives == []


def test_an_event_tool_without_an_event_asks_which(registry, event_of):
    events = {event_of("99118"): 0.45, event_of("99412"): 0.40, "none": 0.15}
    jev = ScriptedRouter(jev_route("get_assessment", {}, 0.9, events=events))
    a = ask(make(registry, jev=jev), "how risky is it?")
    assert a.status == "clarify" and a.text.startswith("Which event?")
    assert [alt["event_id"] for alt in a.alternatives] == [event_of("99118"), event_of("99412")]


def test_a_tool_error_becomes_a_question(registry):
    a = ask(make(registry, link="DENIED"), "/draft 2")
    assert a.status == "clarify" and "MANEUVER" in a.text and "REQUEST_TASKING" in a.text


# -------------------------------------------------------------- narration
def test_an_ungrounded_ai_answer_is_withheld_and_the_facts_shown(registry):
    llm = ScriptedNarrator("There are 12 active events; the worst is EX-DEB 118.")
    a = ask(make(registry, llm=llm), "/events")
    assert a.status == "answered" and a.narrated_by == "template"
    assert a.withheld == {"narrator": "claude", "unsupported": ["12"]}
    assert a.text.startswith("8 active events") and a.grounding["ok"]


def test_a_grounded_ai_answer_is_shown(registry):
    llm = ScriptedNarrator("8 events are active. The most urgent is EX-DEB 560: no Pc, 2.0 h to its commit point.")
    a = ask(make(registry, llm=llm), "/events")
    assert a.status == "answered" and a.narrated_by == "claude" and a.withheld is None
    assert a.text.startswith("8 events are active")


def test_a_narrator_outage_falls_back_to_templates(registry):
    a = ask(make(registry, llm=ScriptedNarrator(error="unreachable")), "/events")
    assert a.status == "answered" and a.narrated_by == "template"
    assert a.fallbacks == [{"from": "claude", "to": "template", "reason": "unreachable"}]


# ---------------------------------------------------------------- writes
def test_a_draft_writes_nothing_until_a_person_confirms_it():
    registry = build_registry()
    assistant = make(registry, link="DENIED")
    a = ask(assistant, "/draft 118 maneuver")
    event_id = a.facts["event_id"]
    assert a.status == "draft" and a.draft_id and registry.ops.entries(event_id) == []

    entry = asyncio.run(assistant.confirm(a.draft_id, author="op2", rationale="agreed at 1400"))
    assert entry["kind"] == "DECISION" and entry["author"] == "op2" and entry["signature_valid"]
    assert entry["body"]["decision"] == "MANEUVER" and entry["body"]["rationale"] == "agreed at 1400"
    assert entry["body"]["drafted_by"] == {"router": "deterministic", "confidence": 1.0, "model": None, "ask_seq": a.audit_seq}
    assert entry["event_ref"]["message_id"] == a.facts["against"]["message_id"]

    with pytest.raises(ToolError) as exc:
        asyncio.run(assistant.confirm(a.draft_id, author="op2"))
    assert exc.value.code == "unknown_draft", "a draft is confirmed once"


def test_a_draft_against_a_superseded_cdm_cannot_be_confirmed():
    import datetime as dt

    at = EPOCH + dt.timedelta(minutes=2)
    registry = build_registry(at)
    assistant = make(registry, link="DENIED")
    a = ask(assistant, "/draft 118 maneuver")
    newer = next(i for i in generate(EPOCH) if i.release_at > at and i.filename.startswith("EX-RED"))
    asyncio.run(registry.conjunctions.ingest(newer.kvn.encode(), "exercise", "EXERCISE"))

    with pytest.raises(ToolError) as exc:
        asyncio.run(assistant.confirm(a.draft_id, author="op2"))
    assert exc.value.code == "stale_draft"
    assert registry.ops.entries(a.facts["event_id"]) == []


def test_unconfirmed_drafts_are_capped_and_the_oldest_is_evicted(caplog):
    assistant = make(build_registry(), link="DENIED", max_drafts=2)
    oldest, middle, newest = (ask(assistant, "/draft 118 monitor") for _ in range(3))

    with pytest.raises(ToolError) as exc:
        asyncio.run(assistant.confirm(oldest.draft_id, author="op2"))
    assert exc.value.code == "unknown_draft", "an evicted draft is gone, as if never made"
    assert asyncio.run(assistant.confirm(newest.draft_id, author="op2"))["kind"] == "DECISION"
    assert asyncio.run(assistant.confirm(middle.draft_id, author="op2"))["kind"] == "DECISION"
    [evicted] = [r.fields for r in caplog.records if r.getMessage() == "Assistant draft evicted"]
    assert evicted == {"ask_seq": oldest.audit_seq, "max_drafts": 2}


def test_the_default_cap_bounds_the_drafts_a_node_holds():
    assistant = make(build_registry(), link="DENIED")
    assert assistant.max_drafts == MAX_DRAFTS and 0 < MAX_DRAFTS <= 1000


def test_the_interface_states_the_cap(tmp_path):
    from sentinel.api import create_app
    from sentinel.api.settings import Settings

    settings = Settings(exercise=False, library=False, web_dist=None, var_dir=str(tmp_path))
    confirm = create_app(settings, start_background=False).openapi()["paths"]["/api/ai/confirm"]["post"]
    assert f"the {MAX_DRAFTS} newest unconfirmed drafts" in confirm["description"]


def test_a_read_only_node_answers_without_drafting_what_it_could_never_record():
    audit = AuditLog(None)
    registry = build_registry()
    assistant = make(registry, link="DENIED", audit=audit, read_only=True)
    a = ask(assistant, "/draft 118 maneuver")
    assert a.status == "clarify" and a.draft_id is None and a.facts is None
    assert a.text == TOOL_QUESTIONS["read_only"] and "read-only" in a.text
    assert a.route["tool"] == "draft_decision", "the request is understood, and refused"
    assert audit.entries()[-1]["status"] == "clarify"
    assert ask(assistant, "/events").status == "answered", "reading still works"


# ----------------------------------------------------------------- audit
def test_every_ask_and_confirm_is_audited_in_a_verifiable_chain():
    audit = AuditLog(None)
    assistant = make(build_registry(), link="DENIED", audit=audit)
    answers = [ask(assistant, text) for text in ("/events", "make me a sandwich", "/draft 2 monitor")]
    asyncio.run(assistant.confirm(answers[-1].draft_id, author="op2"))

    entries = audit.entries()
    assert [e["kind"] for e in entries] == ["ask", "ask", "ask", "confirm"]
    assert [e["status"] for e in entries[:3]] == ["answered", "clarify", "draft"]
    assert entries[0]["route"]["provider"] == "deterministic" and entries[0]["tier"]["link_state"] == "DENIED"
    assert entries[3]["ask_seq"] == answers[-1].audit_seq and entries[3]["author"] == "op2"
    assert audit.verify().ok
