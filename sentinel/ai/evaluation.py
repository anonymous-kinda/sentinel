"""Scoring routers against labelled operator requests (make ai-eval).

A request is labelled with the call a careful operator would expect: the
tool and its arguments, or `tool: null` when the assistant should not act
at all. Routers are scored on the same set, in the same routing context,
through the same confidence gate the assistant applies.

    tool_accuracy       right tool, whatever the confidence (in-scope)
    call_accuracy       right tool and arguments (in-scope)
    coverage            in-scope requests it would act on, not ask about
    selective_accuracy  of everything it would act on, the share right
    abstention          out-of-scope requests it would not act on
    brier, ece          calibration of stated confidence (calibration.py)
"""

from __future__ import annotations

import dataclasses
import json
import pathlib

from .assistant import MIN_CONFIDENCE, gate
from .calibration import brier, ece, reliability
from .router import Route, Router, RouterUnavailable, RoutingContext


@dataclasses.dataclass(frozen=True)
class Case:
    id: str
    text: str
    tool: str | None
    event: str | None = None            # the secondary object's catalog number
    band: str | None = None
    window_h: int | None = None
    decision: str | None = None


@dataclasses.dataclass(frozen=True)
class Outcome:
    case_id: str
    chosen: str | None
    confidence: float
    tool_correct: bool
    call_correct: bool
    acted: bool
    args: dict
    detail: dict = dataclasses.field(default_factory=dict)


def load_cases(path: pathlib.Path) -> list[Case]:
    return [Case(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def expected_args(case: Case, context: RoutingContext) -> dict:
    args: dict = {}
    if case.event is not None:
        args["event_id"] = next(e["event_id"] for e in context.events if e["event_id"].split("-")[1] == case.event)
    for name in ("band", "window_h", "decision"):
        if getattr(case, name) is not None:
            args[name] = getattr(case, name)
    return args


def score(case: Case, route: Route, context: RoutingContext, threshold: float = MIN_CONFIDENCE) -> Outcome:
    acted = gate(route, threshold) is None
    if case.tool is None:
        tool_correct, call_correct = route.tool is None, not acted
    else:
        tool_correct = route.tool == case.tool
        call_correct = tool_correct and route.args == expected_args(case, context)
    return Outcome(case.id, route.tool, route.confidence, tool_correct, call_correct, acted, route.args, route.detail)


def _mean(flags) -> float | None:
    flags = list(flags)
    return sum(flags) / len(flags) if flags else None


def summarize(cases: list[Case], outcomes: list[Outcome]) -> dict:
    in_scope = [o for c, o in zip(cases, outcomes) if c.tool is not None]
    out_of_scope = [o for c, o in zip(cases, outcomes) if c.tool is None]
    choices = [(o.confidence, o.tool_correct) for o in outcomes if o.chosen is not None]
    return {
        "cases": len(outcomes),
        "in_scope": len(in_scope),
        "out_of_scope": len(out_of_scope),
        "tool_accuracy": _mean(o.tool_correct for o in in_scope),
        "call_accuracy": _mean(o.call_correct for o in in_scope),
        "coverage": _mean(o.acted for o in in_scope),
        "selective_accuracy": _mean(o.call_correct for o in outcomes if o.acted),
        "abstention": _mean(not o.acted for o in out_of_scope),
        "brier": brier(choices),
        "ece": ece(choices),
        "reliability": [dataclasses.asdict(b) for b in reliability(choices)],
    }


async def run_eval(router: Router, cases: list[Case], context: RoutingContext) -> dict:
    """Route every case once. A service failure is counted, never scored."""
    scored: list[tuple[Case, Outcome]] = []
    unavailable: dict[str, str] = {}
    for case in cases:
        try:
            route = await router.route(case.text, context)
        except RouterUnavailable as exc:
            unavailable[case.id] = exc.reason
            continue
        scored.append((case, score(case, route, context)))
    summary = summarize([c for c, _ in scored], [o for _, o in scored])
    return {
        "router": router.name,
        "summary": {**summary, "unavailable": len(unavailable)},
        "outcomes": [dataclasses.asdict(o) for _, o in scored],
        "unavailable": unavailable,
    }
