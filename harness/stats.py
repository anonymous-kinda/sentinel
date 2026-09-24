"""Repeated measurements for scenarios that compare two modes (LIMITED).

One run over a real shaped link is one sample. A scenario that compares
modes runs each one N times, reports the median and the range, and checks
that every run measured the link it was meant to measure.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence

MODES = ("edf", "fifo")
TIMES = ("all_summaries", "most_urgent_full", "all_latest_verified", "all_records")
COUNTERS = ("link_up_s", "records_fetched", "record_bytes", "rate_estimate_bytes_per_s")


def spread(values: Sequence[float]) -> dict:
    """Median and range of repeated measurements of one quantity."""
    if not values:
        raise ValueError("no measurements")
    return {"median": statistics.median(values), "min": min(values), "max": max(values), "n": len(values)}


def describe(measured: dict, unit: str = "s", digits: int = 1) -> str:
    """A spread as prose: `median unit (min–max)`, or one value when every run agreed."""
    def number(value: float) -> str:
        return f"{value:,.{digits}f}"

    if measured["min"] == measured["max"]:
        return f"{number(measured['median'])} {unit}"
    return f"{number(measured['median'])} {unit} ({number(measured['min'])}–{number(measured['max'])})"


def summarize(runs: list[dict]) -> dict:
    """Median and range of every time and counter over one mode's runs."""
    summary = {metric: spread([run["times_s"][metric] for run in runs]) for metric in TIMES}
    summary.update({counter: spread([run[counter] for run in runs]) for counter in COUNTERS})
    return summary


def speedup(edf: dict, fifo: dict) -> float:
    """How many times sooner the most urgent full record arrives: a ratio of medians."""
    return round(fifo["most_urgent_full"]["median"] / max(edf["most_urgent_full"]["median"], 0.1), 1)


def run_order(runs_per_mode: int) -> list[str]:
    """Pairs of runs, alternating which mode goes first."""
    order: list[str] = []
    for pair in range(runs_per_mode):
        order += list(MODES) if pair % 2 == 0 else list(reversed(MODES))
    return order


def _canonical(link: dict) -> tuple:
    return sorted(json.dumps(toxic, sort_keys=True) for toxic in link["toxics"]), link["compression"]


def link_mismatches(runs: list[dict], expected: dict) -> list[str]:
    """Every run, and the point in it, where the link (toxics and leaf
    compression) was not `expected`."""
    want = _canonical(expected)
    return [
        f"run {number} ({run['mode']}) at {point}"
        for number, run in enumerate(runs, start=1)
        for point in ("start", "end")
        if _canonical(run["link"][point]) != want
    ]
