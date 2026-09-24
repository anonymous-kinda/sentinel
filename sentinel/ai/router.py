"""Routers turn an operator's words into one catalogued tool call.

A router decides; it never computes. Its output is a Route: the chosen
tool, arguments resolved against the events this node knows, and how sure
it is. The orchestrator - not the router - decides what to do with an
unsure answer.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Protocol

from .catalog import BANDS, TOOLS
from .narrate import event_label


@dataclasses.dataclass(frozen=True)
class RoutingContext:
    events: list[dict]                    # [{"event_id", "label"}], in console order

    @classmethod
    def from_facts(cls, events: list[dict]) -> RoutingContext:
        """From list_events facts: what a router may choose between."""
        return cls([{"event_id": e["event_id"], "label": event_label(e)} for e in events])


@dataclasses.dataclass(frozen=True)
class Route:
    tool: str | None
    args: dict
    confidence: float
    provider: str
    tool_probabilities: dict[str, float] = dataclasses.field(default_factory=dict)
    event_probabilities: dict[str, float] = dataclasses.field(default_factory=dict)
    detail: dict = dataclasses.field(default_factory=dict)


class RouterUnavailable(RuntimeError):
    """A hosted router could not answer; `reason` is stable and low-cardinality."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Router(Protocol):
    name: str

    async def route(self, text: str, context: RoutingContext) -> Route: ...


# ---------------------------------------------------------------- helpers
_WINDOW = re.compile(r"(\d+)\s*(h|hr|hrs|hour|hours|d|day|days)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\b\d+\b")
_DECISION_WORDS = (
    ("no maneuver", "NO_MANEUVER"),
    ("no_maneuver", "NO_MANEUVER"),
    ("maneuver", "MANEUVER"),
    ("monitor", "MONITOR"),
    ("tasking", "REQUEST_TASKING"),
)


def window_hours(text: str) -> int | None:
    m = _WINDOW.search(text)
    if not m:
        return None
    value = int(m.group(1))
    return value * 24 if m.group(2).lower().startswith("d") else value


def band_in(text: str) -> str | None:
    lowered = text.lower()
    return next((b for b in BANDS if re.search(rf"\b{b.lower()}\b", lowered)), None)


def decision_in(text: str) -> str | None:
    lowered = text.lower()
    return next((d for word, d in _DECISION_WORDS if word in lowered), None)


def resolve_event(text: str, events: list[dict], allow_index: bool) -> str | None:
    """An event by console position (slash commands) or by catalog number."""
    for token in _NUMBER.findall(text):
        if allow_index and len(token) <= 2 and 1 <= int(token) <= len(events):
            return events[int(token) - 1]["event_id"]
        if len(token) >= 3:
            for event in events:
                primary, secondary = event["event_id"].split("-")[:2]
                if primary.endswith(token) or secondary.endswith(token):
                    return event["event_id"]
    return None


# ------------------------------------------------------ deterministic router
class DeterministicRouter:
    """No network, no model. Exact for commands, simple rules otherwise."""

    name = "deterministic"
    KEYWORD_CONFIDENCE = 0.6

    async def route(self, text: str, context: RoutingContext) -> Route:
        text = text.strip()
        if text.startswith("/"):
            return self._command(text, context)
        return self._keywords(text, context)

    def _route(self, tool: str | None, args: dict, confidence: float) -> Route:
        return Route(tool, args, confidence, self.name, {tool: confidence} if tool else {})

    def _args(self, tool: str, text: str, context: RoutingContext, allow_index: bool) -> dict:
        args: dict = {}
        if TOOLS[tool].needs_event:
            event_id = resolve_event(text, context.events, allow_index)
            if event_id:
                args["event_id"] = event_id
        if tool == "list_events":
            if band := band_in(text):
                args["band"] = band
            if (hours := window_hours(text)) is not None:
                args["window_h"] = hours
        if tool == "draft_decision" and (decision := decision_in(text)):
            args["decision"] = decision
        return args

    def _command(self, text: str, context: RoutingContext) -> Route:
        verb, _, rest = text[1:].partition(" ")
        tool = {
            "events": "list_events",
            "assess": "get_assessment",
            "explain": "explain_dilution",
            "link": "link_status",
            "queue": "sync_queue",
            "draft": "draft_decision",
        }.get(verb.lower())
        if tool is None:
            return self._route(None, {}, 0.0)
        return self._route(tool, self._args(tool, rest, context, allow_index=True), 1.0)

    def _keywords(self, text: str, context: RoutingContext) -> Route:
        lowered = text.lower()
        has_event = resolve_event(text, context.events, allow_index=False) is not None
        if ("draft" in lowered or "record" in lowered) and decision_in(text):
            tool = "draft_decision"
        elif "dilut" in lowered:
            tool = "explain_dilution"
        elif any(w in lowered for w in ("link", "connection", "connectivity")):
            tool = "link_status"
        elif any(w in lowered for w in ("queue", "waiting", "sync", "pending")):
            tool = "sync_queue"
        elif has_event and any(w in lowered for w in ("risk", "assess", " pc", "probability", "status")):
            tool = "get_assessment"
        elif any(w in lowered for w in ("which", "list", "show", "events", "need action", "red", "amber", "green")):
            tool = "list_events"
        else:
            return self._route(None, {}, 0.0)
        return self._route(tool, self._args(tool, text, context, allow_index=False), self.KEYWORD_CONFIDENCE)
