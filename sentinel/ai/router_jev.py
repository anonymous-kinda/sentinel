"""Jev (TypeSafe AI's System One model) as the routing layer.

Jev answers declared, typed questions with calibrated probabilities in a
single parallel pass; it cannot answer outside the options it is given.
That makes it a router, not an oracle:

  * It chooses which catalogued tool serves the request, and which known
    event the request refers to. Both are Choice questions whose options
    are exactly the catalog and the events on this node.
  * It never supplies a number. Its documented weaknesses include
    arithmetic and dates ("Jev is not a calculator", jev-1.13 jaggedness
    notes), so time windows are parsed deterministically and every figure
    in an answer comes from Sentinel's own code.
  * The model is pinned (jev-1.13.0): confidence thresholds are tuned to
    one version, and aliases move.

Jev is a hosted service with no documented on-premises option; the tier
policy decides when it may be used at all (policy.py).
"""

from __future__ import annotations

import time

from typesafe_sdk import (
    AsyncTypeSafeClient,
    Choice,
    Noul,
    RetryPolicy,
    TypeSafeAPIConnectionError,
    TypeSafeAuthenticationError,
    TypeSafeError,
    TypeSafeInternalServerError,
    TypeSafePermissionDeniedError,
    TypeSafeRateLimitError,
)

from .catalog import BANDS, DECISIONS, TOOLS
from .router import Route, RouterUnavailable, RoutingContext, window_hours

__all__ = ["JEV_MODEL", "NO_RETRY", "JevRouter", "RouterUnavailable"]

JEV_MODEL = "jev-1.13.0"
# One attempt. On a degraded link, waiting out backoff is worse than
# answering with the local router. (The SDK's retry=None means *default*
# retries, not none - found by a test that timed the failure path.)
NO_RETRY = RetryPolicy(max_retries=0)

BAND_CRITERIA = {
    "RED": "Collision probability at or above the maneuver threshold",
    "AMBER": "Elevated collision probability, below the maneuver threshold",
    "GREEN": "Low collision probability",
    "UNASSESSED": "Events with no probability (refused by the engine)",
    "any": "No particular risk band",
}
DECISION_CRITERIA = {
    "MANEUVER": "Plan an avoidance maneuver",
    "NO_MANEUVER": "Decide not to maneuver",
    "MONITOR": "Keep watching; decide on a later update",
    "REQUEST_TASKING": "Ask for more tracking of the objects",
    "none": "The request does not ask for a decision",
}


def _questions(context: RoutingContext) -> dict:
    events = {e["event_id"]: e["label"] for e in context.events}
    events["none"] = "The request does not refer to one specific event"
    return {
        "tool": Choice(
            instructions="Which capability best serves `operator_request`?",
            criteria={name: info.description for name, info in TOOLS.items()},
        ),
        "event": Choice(
            instructions="Which conjunction event in `events` does `operator_request` refer to?",
            criteria=events,
        ),
        "band": Choice(
            instructions="Which risk band, if any, does `operator_request` ask about?",
            criteria={b: BAND_CRITERIA[b] for b in (*BANDS, "any")},
        ),
        "decision": Choice(
            instructions="Which decision, if any, does `operator_request` ask to draft or record?",
            criteria={d: DECISION_CRITERIA[d] for d in (*DECISIONS, "none")},
        ),
        "consequential": Noul(
            instructions="`operator_request` asks the system to take or record an action with operational consequence, rather than to show information",
        ),
    }


def _reason(exc: Exception) -> str:
    if isinstance(exc, (TypeSafeAuthenticationError, TypeSafePermissionDeniedError)):
        return "authentication"
    if isinstance(exc, TypeSafeRateLimitError):
        return "rate_limited"
    if isinstance(exc, TypeSafeInternalServerError):
        return "server_error"
    if isinstance(exc, TypeSafeAPIConnectionError):
        return "unreachable"
    return "error"


class JevRouter:
    name = "jev"

    def __init__(self, client):
        """`client`: a typesafe_sdk.AsyncTypeSafeClient (injected for tests)."""
        self._client = client

    @classmethod
    def from_env(cls, transport=None) -> JevRouter:
        """Client from TYPESAFE_API_KEY; `transport` is for tests."""
        return cls(AsyncTypeSafeClient(model=JEV_MODEL, timeout=5.0, retry=NO_RETRY, transport=transport))

    async def route(self, text: str, context: RoutingContext) -> Route:
        state = {"operator_request": text, "events": context.events}
        questions = _questions(context)
        started = time.monotonic()
        try:
            response = await self._client.system_one(state=state, questions=questions, model=JEV_MODEL)
        except TypeSafeError as exc:
            raise RouterUnavailable(_reason(exc)) from exc
        latency_ms = (time.monotonic() - started) * 1000
        return self._to_route(text, response, latency_ms)

    def _to_route(self, text, response, latency_ms) -> Route:
        answers = response.answers
        tool = answers["tool"].choice
        event = answers["event"].choice
        args: dict = {}
        if TOOLS[tool].needs_event and event != "none":
            args["event_id"] = event
        if tool == "list_events":
            if answers["band"].choice != "any":
                args["band"] = answers["band"].choice
            if (hours := window_hours(text)) is not None:
                args["window_h"] = hours
        if tool == "draft_decision" and answers["decision"].choice != "none":
            args["decision"] = answers["decision"].choice

        raw = response.raw_http_response
        return Route(
            tool=tool,
            args=args,
            confidence=float(answers["tool"].confidence),
            provider=self.name,
            tool_probabilities={k: float(v) for k, v in answers["tool"].probabilities.items()},
            event_probabilities={k: float(v) for k, v in answers["event"].probabilities.items()},
            detail={
                "model": response.model,
                "latency_ms": round(latency_ms, 1),
                "request_bytes": len(raw.request.content),
                "response_bytes": len(raw.content),
                "request_id": response.request_id,
                "consequential": float(answers["consequential"].noul),
                "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
            },
        )
