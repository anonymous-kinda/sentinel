"""The assistant: route, gate, act, narrate, check, audit.

    text --router (Jev | local)-------> Route: tool, arguments, confidence
         --gates----------------------> ask back when unsure, or when an
                                        event or decision is missing
         --tool-----------------------> facts (code computes every number)
         --narrator (Claude | template)> prose
         --grounding guard------------> an AI answer stating a number the
                                        facts do not is withheld
         --audit----------------------> one hash-chained line per ask

The tier policy picks router and narrator from the measured link state
and the classification marking; a hosted service that fails falls back
to the local one, and the answer says so. A tool that writes yields a
draft, and only `confirm` - a person - records it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import secrets
from collections.abc import Callable

from ..obs import get_logger
from .catalog import DECISIONS, TOOLS
from .grounding import check_grounding
from .narrate import Narrator, NarratorUnavailable, TemplateNarrator
from .policy import TierInputs, decide
from .router import DeterministicRouter, Route, Router, RouterUnavailable, RoutingContext
from .tools import ToolError, ToolRegistry

log = get_logger(__name__)

MIN_CONFIDENCE = 0.5
# Unconfirmed drafts a node holds; past this the oldest is forgotten.
MAX_DRAFTS = 100
COMMANDS = "Try /events [red|amber] [48h], /assess <n>, /explain <n>, /link, /queue or /draft <n> <decision>."
TOOL_QUESTIONS = {
    "missing_event": "Which event?",
    "unknown_event": "That event is not on this node. /events lists the active ones.",
    "missing_decision": f"Which decision: {', '.join(DECISIONS)}?",
    "invalid_decision": f"A decision is one of {', '.join(DECISIONS)}.",
    "invalid_band": "Bands are RED, AMBER, GREEN and UNASSESSED.",
    "unknown_tool": COMMANDS,
    "read_only": "This node is read-only: it answers questions but records no decisions, so it drafts none.",
}


def gate(route: Route, min_confidence: float = MIN_CONFIDENCE) -> str | None:
    """Why the assistant would ask back instead of acting; None to act.
    The eval scores routers through this same gate. It fails closed: a
    confidence that is not a probability (NaN, above 1) is not a confident one."""
    if route.tool not in TOOLS or not min_confidence <= route.confidence <= 1.0:
        return "unsure"
    if TOOLS[route.tool].needs_event and "event_id" not in route.args:
        return "which_event"
    return None


@dataclasses.dataclass
class Answer:
    status: str                         # answered | clarify | draft
    text: str
    tier: dict
    route: dict | None = None
    facts: dict | None = None
    narrated_by: str | None = None
    grounding: dict | None = None
    withheld: dict | None = None        # an AI answer that failed the guard
    alternatives: list[dict] = dataclasses.field(default_factory=list)
    fallbacks: list[dict] = dataclasses.field(default_factory=list)
    draft_id: str | None = None
    audit_seq: int | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class _Draft:
    facts: dict
    route: dict
    ask_seq: int


def _sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class Assistant:
    def __init__(
        self,
        tools: ToolRegistry,
        *,
        link_state: Callable[[], str],
        marking: str,
        cloud_opt_in: bool,
        audit,
        clock,
        jev: Router | None = None,
        llm: Narrator | None = None,
        min_confidence: float = MIN_CONFIDENCE,
        max_drafts: int = MAX_DRAFTS,
        read_only: bool = False,
    ):
        self.tools = tools
        self.marking = marking
        self.cloud_opt_in = cloud_opt_in
        self.audit = audit
        self.clock = clock
        self.min_confidence = min_confidence
        self.max_drafts = max_drafts
        self.read_only = read_only
        self._link_state = link_state
        self._routers: dict[str, Router] = {"deterministic": DeterministicRouter(), **({"jev": jev} if jev else {})}
        self._narrators: dict[str, Narrator] = {"template": TemplateNarrator(), **({"claude": llm} if llm else {})}
        self._drafts: dict[str, _Draft] = {}

    # ------------------------------------------------------------------ tier
    def tier(self) -> dict:
        link_state = self._link_state()
        decision = decide(
            TierInputs(link_state, self.marking, "jev" in self._routers, "claude" in self._narrators, self.cloud_opt_in)
        )
        return {
            "router": decision.router,
            "narrator": decision.narrator,
            "reason": decision.reason,
            "link_state": link_state,
            "marking": self.marking,
        }

    # ------------------------------------------------------------------- ask
    async def ask(self, text: str, author: str) -> Answer:
        answer = await self._answer(text, self.tier())
        record = {
            "kind": "ask",
            "author": author,
            "question": text,
            "status": answer.status,
            "tier": answer.tier,
            "route": answer.route,
            "narrated_by": answer.narrated_by,
            "grounding": answer.grounding,
            "withheld": answer.withheld,
            "fallbacks": answer.fallbacks,
            "answer": answer.text,
            "facts_sha256": None if answer.facts is None else _sha256(answer.facts),
        }
        answer.audit_seq = self.audit.append(record, at=self.clock.now().isoformat())["seq"]
        if answer.status == "draft":
            answer.draft_id = secrets.token_hex(8)
            self._hold_draft(answer.draft_id, _Draft(answer.facts, answer.route, answer.audit_seq))
        return answer

    def _hold_draft(self, draft_id: str, draft: _Draft) -> None:
        """Keep a draft for confirmation, forgetting the oldest past max_drafts:
        confirming a forgotten draft is `unknown_draft`, as if never made."""
        self._drafts[draft_id] = draft
        while len(self._drafts) > self.max_drafts:
            evicted = self._drafts.pop(next(iter(self._drafts)))
            log.warning("Assistant draft evicted", ask_seq=evicted.ask_seq, max_drafts=self.max_drafts)

    async def _answer(self, text: str, tier: dict) -> Answer:
        fallbacks: list[dict] = []
        context = self._context()
        route = await self._route(text, context, tier["router"], fallbacks)
        answer = Answer("clarify", "", tier, route=dataclasses.asdict(route), fallbacks=fallbacks)

        held = gate(route, self.min_confidence)
        if held == "unsure":
            answer.text, answer.alternatives = self._unsure(route)
            return answer
        if self.read_only and TOOLS[route.tool].writes:
            answer.text = TOOL_QUESTIONS["read_only"]
            return answer
        if held == "which_event":
            answer.text, answer.alternatives = self._which_event(route, context)
            return answer
        try:
            facts = self.tools.execute(route.tool, route.args)
        except ToolError as exc:
            answer.text = TOOL_QUESTIONS.get(exc.code, COMMANDS)
            return answer

        answer.facts = facts
        answer.text, answer.narrated_by, answer.withheld = await self._narrate(
            text, route.tool, facts, tier["narrator"], fallbacks
        )
        answer.grounding = dataclasses.asdict(check_grounding(answer.text, facts, text))
        answer.status = "draft" if TOOLS[route.tool].writes else "answered"
        return answer

    def _context(self) -> RoutingContext:
        return RoutingContext.from_facts(self.tools.execute("list_events", {})["events"])

    async def _route(self, text: str, context: RoutingContext, name: str, fallbacks: list[dict]) -> Route:
        try:
            return await self._routers[name].route(text, context)
        except RouterUnavailable as exc:
            log.warning("AI router unavailable", router=name, reason=exc.reason)
            fallbacks.append({"from": name, "to": "deterministic", "reason": exc.reason})
            return await self._routers["deterministic"].route(text, context)

    async def _narrate(
        self, question: str, tool: str, facts: dict, name: str, fallbacks: list[dict]
    ) -> tuple[str, str, dict | None]:
        """(text, narrated_by, withheld). Templates are the floor: always
        available, always grounded (tests/ai/test_narrate.py)."""
        withheld = None
        if name != "template":
            try:
                text = await self._narrators[name].narrate(question, tool, facts)
            except NarratorUnavailable as exc:
                log.warning("AI narrator unavailable", narrator=name, reason=exc.reason)
                fallbacks.append({"from": name, "to": "template", "reason": exc.reason})
            else:
                grounding = check_grounding(text, facts, question)
                if grounding.ok:
                    return text, name, None
                log.warning("AI answer withheld", narrator=name, tool=tool, unsupported=len(grounding.unsupported))
                withheld = {"narrator": name, "unsupported": grounding.unsupported}
        return await self._narrators["template"].narrate(question, tool, facts), "template", withheld

    # ----------------------------------------------------------- asking back
    @staticmethod
    def _unsure(route: Route) -> tuple[str, list[dict]]:
        ranked = sorted(route.tool_probabilities.items(), key=lambda kv: kv[1], reverse=True)
        alternatives = [
            {"tool": tool, "p": p, "description": TOOLS[tool].description} for tool, p in ranked[:2] if tool in TOOLS
        ]
        if route.tool is None or not alternatives:
            return f"I couldn't match that to something I can do. {COMMANDS}", []
        options = "; or ".join(f"{a['description']} (p {a['p']:.2f})" for a in alternatives)
        return f"I'm not sure what you need. Did you mean: {options}?", alternatives

    @staticmethod
    def _which_event(route: Route, context: RoutingContext) -> tuple[str, list[dict]]:
        labels = {e["event_id"]: e["label"] for e in context.events}
        if not labels:
            return "There are no active events on this node.", []
        ranked = sorted(route.event_probabilities.items(), key=lambda kv: kv[1], reverse=True)
        candidates = [e for e, _ in ranked if e in labels][:3] or list(labels)[:3]
        alternatives = [
            {"event_id": e, "label": labels[e], "p": route.event_probabilities.get(e)} for e in candidates
        ]
        return "Which event? " + "; ".join(a["label"] for a in alternatives) + ".", alternatives

    # --------------------------------------------------------------- confirm
    async def confirm(self, draft_id: str, author: str, rationale: str = "") -> dict:
        """A person turns a draft into a signed DECISION. Once only."""
        draft = self._drafts.pop(draft_id, None)
        if draft is None:
            raise ToolError("unknown_draft", draft_id)
        provenance = {
            "router": draft.route["provider"],
            "confidence": draft.route["confidence"],
            "model": draft.route["detail"].get("model"),
            "ask_seq": draft.ask_seq,
        }
        entry = await self.tools.record_decision(draft.facts, author, rationale, provenance)
        self.audit.append(
            {"kind": "confirm", "author": author, "draft_id": draft_id, "ask_seq": draft.ask_seq, "entry": entry["digest"]},
            at=self.clock.now().isoformat(),
        )
        log.info("AI draft confirmed", event_id=draft.facts["event_id"], ask_seq=draft.ask_seq)
        return entry
