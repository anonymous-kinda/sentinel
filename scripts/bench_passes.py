#!/usr/bin/env python3
"""Time the pass engine: the whole imaging catalog over 24 h at one unit.

    uv run python scripts/bench_passes.py            # exercise unit, 5 runs

Each run builds a fresh provider (no cached satellites), predicts every
catalogued imager's windows and computes the gaps. Offline: the vendored
snapshot and Skyfield's bundled timescale. The default position is an
exercise position (ORIGINATOR=SENTINEL-EXERCISE), not a real unit.
"""

import argparse
import datetime as dt
import pathlib
import statistics
import time

from sentinel.passes.catalog import load_catalog
from sentinel.passes.elements import load_omm, match_catalog
from sentinel.passes.gaps import unobserved_gaps
from sentinel.passes.model import Unit
from sentinel.passes.providers.skyfield_local import SkyfieldProvider

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


if __name__ == "__main__":
    main()
