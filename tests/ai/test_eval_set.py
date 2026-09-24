"""The labelled routing set is well-formed, and the eval runs end to end."""

import asyncio
import collections
import pathlib

from sentinel.ai.catalog import BANDS, DECISIONS, TOOLS
from sentinel.ai.evaluation import load_cases, run_eval
from sentinel.ai.router import DeterministicRouter, RoutingContext

EVAL_SET = pathlib.Path(__file__).resolve().parents[2] / "evals" / "routing.jsonl"


def test_the_set_covers_every_tool_and_out_of_scope_requests(registry):
    cases = load_cases(EVAL_SET)
    assert len(cases) >= 60 and len({c.id for c in cases}) == len(cases)
    per_tool = collections.Counter(c.tool for c in cases)
    assert set(per_tool) == set(TOOLS) | {None}
    assert min(per_tool.values()) >= 6

    known = {e["secondary_id"] for e in registry.execute("list_events", {})["events"]}
    for c in cases:
        needs_event = c.tool is not None and TOOLS[c.tool].needs_event
        assert (c.event is not None) == needs_event, c.id
        assert c.event is None or c.event in known, c.id
        assert c.band is None or c.band in BANDS, c.id
        assert c.decision is None or c.decision in DECISIONS, c.id
        assert (c.decision is not None) == (c.tool == "draft_decision"), c.id


def test_the_baseline_is_scored_on_every_case(registry):
    cases = load_cases(EVAL_SET)
    context = RoutingContext.from_facts(registry.execute("list_events", {})["events"])
    report = asyncio.run(run_eval(DeterministicRouter(), cases, context))
    s = report["summary"]
    assert report["router"] == "deterministic" and s["cases"] == len(cases) and s["unavailable"] == 0
    for metric in ("tool_accuracy", "call_accuracy", "coverage", "selective_accuracy", "abstention", "brier"):
        assert 0.0 <= s[metric] <= 1.0, metric
