"""Readiness check for the hosted providers (`make ai-live-check`).

One real call per provider whose key is set, through the production
adapters: Jev routes one operator question, and Claude phrases one tool's
facts, which the number-grounding guard then checks. A key that is not set
is reported with what the call would do, and it is not a failure. A
configured call that fails is a failure, named by the adapter's stable
reason code.

Nothing is written. Publishing eval numbers is `make ai-eval`'s job. The
report shows reason codes, never exception text, so a service that echoes
a key in an error body cannot put it on the screen. For the same reason the
SDKs' DEBUG wire logs, which carry response bodies, are held at INFO while
the calls run.

This module sees protocols only; the caller injects the adapters, so the
hosted SDKs stay confined to router_jev.py and narrate_claude.py (ADR-007).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from typing import Literal, Protocol

from ..obs import get_logger
from .grounding import check_grounding
from .narrate import Narration, NarratorUnavailable
from .router import Router, RouterUnavailable, RoutingContext

log = get_logger(__name__)

JEV_KEY = "TYPESAFE_API_KEY"
CLAUDE_KEY = "ANTHROPIC_API_KEY"
GUIDE = 'docs/technical-guide.md ("The AI assistant pipeline")'
NEXT = "Next: make ai-eval  (scores the routers on evals/routing.jsonl and rewrites docs/ai-eval.md; Jev only with its key)"
HOW_TO_SET = "Set a key: copy .env.example to .env and fill it in (this command reads it), or export it."
LABEL_WIDTH = 12
# Loggers that write request and response bodies at DEBUG.
WIRE_LOGGERS = ("typesafe_sdk", "anthropic", "httpx", "httpx2", "httpcore")
HINTS = {
    "authentication": "the service rejected the key",
    "rate_limited": "the service is rate-limiting this key; wait, then rerun",
    "server_error": "the service answered with a server error; rerun later",
    "unreachable": "no answer from the service (network, proxy, DNS or, for Jev, its time budget)",
    "timeout": "no answer within the call's time budget",
    "refused": "the model declined to answer",
    "truncated": "the answer ran past its token budget",
    "empty": "the answer had no text",
    "error": "an error the adapter does not classify; the log line on stderr names its type",
}

Rows = list[tuple[str, str]]


class MeteredNarrator(Protocol):
    async def narration(self, question: str, tool: str, facts: dict) -> Narration: ...


@dataclasses.dataclass(frozen=True)
class Check:
    """One provider: the key it needs and the one real call it makes."""

    name: str
    key_var: str
    plan: str                                   # what the call does, once the key is set
    read: str                                   # where to read about it
    call: Callable[[], Awaitable[Rows]]


@dataclasses.dataclass(frozen=True)
class Result:
    check: Check
    status: Literal["ok", "not configured", "FAILED"]
    rows: Rows


# ------------------------------------------------------------------ checks
def jev_check(make_router: Callable[[], Router], question: str, context: RoutingContext) -> Check:
    """Route `question` once against `context`."""

    async def call() -> Rows:
        route = await make_router().route(question, context)
        d = route.detail
        return [
            ("question", question),
            ("tool", f"{route.tool} {json.dumps(route.args)}"),
            ("confidence", f"{route.confidence:.2f}"),
            ("model", str(d["model"])),
            ("latency", f"{d['latency_ms']} ms"),
            ("bytes", f"request {d['request_bytes']:,}, response {d['response_bytes']:,}"),
            ("request id", str(d["request_id"])),
        ]

    plan = (
        f'routes "{question}" through JevRouter.from_env() against the exercise scenario '
        f"({len(context.events)} events), then reports the tool, arguments, confidence, latency and bytes"
    )
    return Check("Jev routing", JEV_KEY, plan, f"{GUIDE}, evals/README.md", call)


def claude_check(make_narrator: Callable[[], MeteredNarrator], question: str, tool: str, facts: dict) -> Check:
    """Phrase `facts`, which `tool` returned for `question`, once; then check its numbers."""

    async def call() -> Rows:
        n = await make_narrator().narration(question, tool, facts)
        return [
            ("question", question),
            ("facts", f"{tool}, computed by Sentinel's own code"),
            ("model", n.model),
            ("latency", f"{n.latency_ms} ms"),
            ("grounding", _grounding(n.text, facts, question)),
            ("tokens", f"input {n.input_tokens:,}, output {n.output_tokens:,}"),
            ("request id", str(n.request_id)),
            ("answer", n.text),
        ]

    plan = (
        f"phrases the {tool} facts for that question through ClaudeNarrator.from_env(), checks every number "
        "with the grounding guard, then reports the model, latency, grounding and tokens"
    )
    return Check("Claude narration", CLAUDE_KEY, plan, f"{GUIDE}, docs/system-design.md (ADR-007)", call)


def _grounding(text: str, facts: dict, question: str) -> str:
    result = check_grounding(text, facts, question)
    if result.ok:
        return "passed: every number is in the facts or the question"
    unsupported = ", ".join(result.unsupported)
    return f"failed: {unsupported} not in the facts; the assistant would withhold this and show the template"


# --------------------------------------------------------------------- run
async def run_checks(checks: Sequence[Check], env: Mapping[str, str]) -> list[Result]:
    with _wire_logs_held_at_info():
        return [await _run(check, env) for check in checks]


@contextlib.contextmanager
def _wire_logs_held_at_info() -> Iterator[None]:
    loggers = [logging.getLogger(name) for name in WIRE_LOGGERS]
    saved = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(max(logging.INFO, logger.getEffectiveLevel()))
    try:
        yield
    finally:
        for logger, level in zip(loggers, saved, strict=True):
            logger.setLevel(level)


async def _run(check: Check, env: Mapping[str, str]) -> Result:
    if not env.get(check.key_var, "").strip():
        rows = [("missing", f"{check.key_var} is not set"), ("once set", check.plan), ("read", check.read)]
        return Result(check, "not configured", rows)
    try:
        rows = await check.call()
    except (RouterUnavailable, NarratorUnavailable) as exc:
        # The type, never the message: a service's error text can echo the key.
        error = type(exc.__cause__).__name__ if exc.__cause__ else None
        log.warning("Hosted AI live check failed", provider=check.name, reason=exc.reason, error=error)
        hint = HINTS.get(exc.reason, HINTS["error"])
        return Result(check, "FAILED", [("reason", f"{exc.reason}: {hint}")])
    log.info("Hosted AI live check passed", provider=check.name)
    return Result(check, "ok", rows)


def exit_code(results: Sequence[Result]) -> int:
    """1 when a configured call failed; a key that is not set is not a failure."""
    return 1 if any(r.status == "FAILED" for r in results) else 0


# ------------------------------------------------------------------ report
def render(results: Sequence[Result]) -> str:
    lines = ["Hosted AI live check: one real call per provider whose key is set. Writes nothing.", ""]
    for result in results:
        lines.append(f"{result.check.name}: {result.status}")
        lines += [_row(label, value) for label, value in result.rows]
        lines.append("")
    if all(r.status == "not configured" for r in results):
        lines.append("No key is set, so no call was made. A key that is not set is not a failure.")
    if any(r.status == "not configured" for r in results):
        lines.append(HOW_TO_SET)
    lines.append(NEXT)
    return "\n".join(lines)


def _row(label: str, value: str) -> str:
    continued = value.replace("\n", "\n" + " " * (2 + LABEL_WIDTH))
    return f"  {label:<{LABEL_WIDTH}}{continued}"
