#!/usr/bin/env python3
"""Generate docs/ai-eval.md: routers scored on the labelled routing set.

The deterministic baseline always runs. Jev runs only when TYPESAFE_API_KEY
is set; its raw results are saved to docs/ai-eval-jev.json and reused by
later runs without a key, labelled with the run date, model and eval-set
hash. Nothing in the Jev column is produced without a real Jev run.

    uv run python scripts/ai_eval.py
"""

import asyncio
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel import localenv  # noqa: E402
from sentinel.ai.evaluation import load_cases, run_eval  # noqa: E402
from sentinel.ai.router import DeterministicRouter, RoutingContext  # noqa: E402
from sentinel.ai.tools import event_facts  # noqa: E402
from sentinel.bus import InProcessBus  # noqa: E402
from sentinel.clock import FixedClock  # noqa: E402
from sentinel.conjunction.exercise import generate  # noqa: E402
from sentinel.conjunction.service import ConjunctionService  # noqa: E402
from sentinel.conjunction.store import ConjunctionStore  # noqa: E402

EVAL_SET = ROOT / "evals" / "routing.jsonl"
OUT = ROOT / "docs" / "ai-eval.md"
JEV_RESULTS = ROOT / "docs" / "ai-eval-jev.json"
SVG = ROOT / "docs" / "img" / "ai-reliability.svg"
EPOCH = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.UTC)
NOW = EPOCH + dt.timedelta(hours=1)
METRICS = [
    ("tool_accuracy", "Right tool (in scope)"),
    ("call_accuracy", "Right tool and arguments (in scope)"),
    ("coverage", "Acted instead of asking (in scope)"),
    ("selective_accuracy", "Right, of everything it acted on"),
    ("abstention", "Did not act (out of scope)"),
    ("brier", "Brier score (lower is better)"),
    ("ece", "Expected calibration error (lower is better)"),
]


def exercise_service() -> ConjunctionService:
    """The exercise scenario one hour in: every CDM released by then, ingested and assessed."""
    service = ConjunctionService(ConjunctionStore(), InProcessBus(), FixedClock(NOW))
    for item in generate(EPOCH):
        if item.release_at <= NOW:
            asyncio.run(service.ingest(item.kvn.encode(), "exercise", "EXERCISE"))
    return service


def routing_context(service: ConjunctionService) -> RoutingContext:
    """The events a router chooses from."""
    return RoutingContext.from_facts([event_facts(s) for s in service.list_events()])


def jev_report(cases, context, set_hash: str) -> dict | None:
    if os.environ.get("TYPESAFE_API_KEY"):
        from sentinel.ai.router_jev import JEV_MODEL, JevRouter

        report = asyncio.run(run_eval(JevRouter.from_env(), cases, context))
        report.update(model=JEV_MODEL, eval_set_sha256=set_hash, run_at=dt.datetime.now(dt.UTC).isoformat())
        JEV_RESULTS.write_text(json.dumps(report, indent=1) + "\n")
        return report
    if JEV_RESULTS.exists():
        return json.loads(JEV_RESULTS.read_text())
    return None


def fmt(value) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def mean_detail(report: dict, key: str) -> float | None:
    values = [o["detail"][key] for o in report["outcomes"] if key in o["detail"]]
    return sum(values) / len(values) if values else None


def svg(reports: dict[str, dict]) -> str:
    size, pad = 360, 40
    plot = size - 2 * pad

    def xy(conf: float, acc: float) -> tuple[float, float]:
        return pad + conf * plot, size - pad - acc * plot

    colours = {"deterministic": "#8a8f98", "jev": "#2f6fdf"}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" font-family="sans-serif" font-size="11">',
        f'<rect width="{size}" height="{size}" fill="#fff"/>',
        f'<rect x="{pad}" y="{pad}" width="{plot}" height="{plot}" fill="none" stroke="#ccc"/>',
        f'<line x1="{pad}" y1="{size - pad}" x2="{size - pad}" y2="{pad}" stroke="#bbb" stroke-dasharray="4 3"/>',
        *(
            f'<text x="{pad + t * plot}" y="{size - pad + 14}" text-anchor="middle">{t:g}</text>'
            f'<text x="{pad - 6}" y="{size - pad - t * plot + 4}" text-anchor="end">{t:g}</text>'
            for t in (0, 0.5, 1)
        ),
        f'<text x="{size / 2}" y="{size - 8}" text-anchor="middle">stated confidence</text>',
        f'<text x="12" y="{size / 2}" text-anchor="middle" transform="rotate(-90 12 {size / 2})">observed accuracy</text>',
    ]
    for row, (name, report) in enumerate(reports.items()):
        colour = colours.get(name, "#000")
        for b in report["summary"]["reliability"]:
            if b["count"]:
                x, y = xy(b["confidence"], b["accuracy"])
                r = 3 + min(b["count"], 30) / 3
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{colour}" fill-opacity="0.6"/>')
        parts.append(f'<circle cx="{pad + 10}" cy="{pad + 14 + row * 16}" r="5" fill="{colour}"/>')
        parts.append(f'<text x="{pad + 20}" y="{pad + 18 + row * 16}">{name}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    cases = load_cases(EVAL_SET)
    set_hash = hashlib.sha256(EVAL_SET.read_bytes()).hexdigest()
    context = routing_context(exercise_service())
    reports = {"deterministic": asyncio.run(run_eval(DeterministicRouter(), cases, context))}
    jev = jev_report(cases, context, set_hash)
    stale = jev is not None and jev.get("eval_set_sha256") != set_hash
    if jev is not None and not stale:
        reports["jev"] = jev

    lines: list[str] = []
    w = lines.append
    w("# Assistant routing eval")
    w("")
    w("Generated by `scripts/ai_eval.py` (`make ai-eval`). Do not edit by hand.")
    w("")
    w(f"- Eval set: `evals/routing.jsonl`, {len(cases)} labelled requests "
      f"({sum(c.tool is not None for c in cases)} in scope, {sum(c.tool is None for c in cases)} out of scope), "
      f"sha256 `{set_hash[:16]}`. See `evals/README.md` for how the labels were written and their limits.")
    w(f"- Routing context: the exercise scenario at T+1 h, {len(context.events)} active events.")
    w("- Every router passes through the assistant's own confidence gate (act at 0.5 or above) and needs-event check.")
    if jev is None:
        w("- **Jev: not run.** `TYPESAFE_API_KEY` was not set, and no saved Jev run exists. No Jev numbers are shown.")
    elif stale:
        w("- **Jev: saved run is stale** (made on a different eval set). Rerun with `TYPESAFE_API_KEY` set.")
    else:
        w(f"- Jev: model `{jev['model']}`, run {jev['run_at'][:16]}Z, {jev['summary']['unavailable']} requests unavailable.")
    w("")
    w("## Results")
    w("")
    w("| Metric | " + " | ".join(reports) + " |")
    w("|---|" + "---|" * len(reports))
    for key, label in METRICS:
        w(f"| {label} | " + " | ".join(fmt(r["summary"][key]) for r in reports.values()) + " |")
    w("")
    if "jev" in reports:
        w("## Cost of a Jev routing decision")
        w("")
        w("| Mean latency (ms) | Mean request bytes | Mean response bytes |")
        w("|---|---|---|")
        w(f"| {fmt(mean_detail(jev, 'latency_ms'))} | {fmt(mean_detail(jev, 'request_bytes'))} | "
          f"{fmt(mean_detail(jev, 'response_bytes'))} |")
        w("")
    w("## Reliability")
    w("")
    w("![reliability diagram](img/ai-reliability.svg)")
    w("")
    for name, report in reports.items():
        w(f"**{name}**")
        w("")
        w("| Confidence bin | Cases | Mean confidence | Observed accuracy |")
        w("|---|---|---|---|")
        for b in report["summary"]["reliability"]:
            if b["count"]:
                w(f"| {b['lo']:.1f}-{b['hi']:.1f} | {b['count']} | {fmt(b['confidence'])} | {fmt(b['accuracy'])} |")
        w("")
    w("## Misses")
    w("")
    by_id = {c.id: c for c in cases}
    for name, report in reports.items():
        misses = [o for o in report["outcomes"] if not o["call_correct"]]
        w(f"**{name}**: {len(misses)} of {len(report['outcomes'])}")
        w("")
        if misses:
            w("| Case | Request | Expected | Got | Confidence | Acted |")
            w("|---|---|---|---|---|---|")
            for o in misses:
                c = by_id[o["case_id"]]
                w(f"| {c.id} | {c.text} | {c.tool or '(do not act)'} | {o['chosen'] or '(none)'} "
                  f"{json.dumps(o['args']) if o['args'] else ''} | {o['confidence']:.2f} | {'yes' if o['acted'] else 'no'} |")
            w("")

    OUT.write_text("\n".join(lines))
    SVG.parent.mkdir(parents=True, exist_ok=True)
    SVG.write_text(svg(reports))
    print(f"wrote {OUT.relative_to(ROOT)} ({', '.join(reports)})")


if __name__ == "__main__":
    localenv.load()
    main()
