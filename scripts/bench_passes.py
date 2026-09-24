#!/usr/bin/env python3
"""Time the pass engine: the whole imaging catalog over 24 h at one unit.

    uv run python scripts/bench_passes.py            # exercise unit, 5 runs

Each run builds a fresh provider (no cached satellites), predicts every
catalogued imager's windows and computes the gaps. Offline: the vendored
snapshot and Skyfield's bundled timescale. The default position is an
exercise position (ORIGINATOR=SENTINEL-EXERCISE), not a real unit.

Then the node's PassService, as the API calls it: a cold call, a repeat in
the same minute (served from the cache), and a call a minute later (a new
interval, recomputed on the provider the service keeps).
"""

import argparse
import asyncio
import datetime as dt
import pathlib
import statistics
import tempfile
import time

from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock
from sentinel.passes.catalog import load_catalog
from sentinel.passes.element_store import ElementStore
from sentinel.passes.elements import load_omm, match_catalog
from sentinel.passes.gaps import unobserved_gaps
from sentinel.passes.model import Unit
from sentinel.passes.providers.skyfield_local import SkyfieldProvider
from sentinel.passes.service import PassService
from sentinel.passes.unit import UnitFile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "fixtures" / "omm" / "celestrak-resource-20260924.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lat", type=float, default=35.26)
    parser.add_argument("--lon", type=float, default=-116.68)
    parser.add_argument("--start", default="2026-09-24T06:00:00+00:00")
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()

    unit = Unit(unit_id="EXERCISE", lat_deg=args.lat, lon_deg=args.lon)
    start = dt.datetime.fromisoformat(args.start)
    end = start + dt.timedelta(hours=args.hours)
    match = match_catalog(load_catalog(), load_omm(SNAPSHOT))

    timings_s = []
    for _ in range(args.repeat):
        began = time.perf_counter()
        windows = SkyfieldProvider(match.element_sets).windows(unit, match.imagers, start, end)
        gaps = unobserved_gaps(windows, start, end)
        timings_s.append(time.perf_counter() - began)

    print(f"imagers {len(match.imagers)}  skipped {len(match.skipped)}  interval {args.hours:g} h")
    print(f"windows {len(windows)}  usable {sum(w.usable for w in windows)}  stale {sum(w.stale for w in windows)}")
    print(f"gaps {len(gaps)}  unobserved {sum(g.duration_s for g in gaps) / 3600:.2f} h")
    print(f"wall time over {args.repeat} runs: median {statistics.median(timings_s):.3f} s, max {max(timings_s):.3f} s")
    _service_timings(unit, start, args.hours)


def _timed(fn) -> float:
    began = time.perf_counter()
    fn()
    return time.perf_counter() - began


def _service_timings(unit: Unit, start: dt.datetime, hours: float) -> None:
    store = ElementStore()
    store.load_snapshot(SNAPSHOT, "celestrak")
    clock = FixedClock(start)
    with tempfile.TemporaryDirectory() as var:
        service = PassService(store, load_catalog(), clock, UnitFile(pathlib.Path(var) / "unit.json"), InProcessBus(), "bench")
        asyncio.run(service.set_unit(unit))
        cold = _timed(lambda: service.passes(hours))
        cached = _timed(lambda: service.passes(hours))
        clock.advance(60)
        next_minute = _timed(lambda: service.passes(hours))
    print(f"service: cold {cold:.3f} s, same minute (cached) {cached * 1000:.2f} ms, next minute {next_minute:.3f} s")


if __name__ == "__main__":
    main()
