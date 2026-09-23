#!/usr/bin/env python3
"""Demonstrate the dilution pathology on a single conjunction.

Holds the geometry fixed - same miss distance, same hard-body radius, same
relative velocity - and varies only the quality of the orbit determination.
Then prints what an operator would see.

Run:  python3 scripts/dilution_demo.py
"""

import sys
import pathlib

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sentinel.risk import assess
from tests.conftest import make_conjunction

MISS_M = 1000.0
RADIUS_M = 0.5  # per object, so HBR = 1 m
BOUNDARY = MISS_M / np.sqrt(2.0)


def main() -> None:
    print()
    print(f"  Conjunction geometry held constant:")
    print(f"    miss distance      {MISS_M:,.0f} m")
    print(f"    hard-body radius   {2 * RADIUS_M:,.0f} m")
    print(f"    relative speed     15,000 m/s")
    print()
    print(f"  Only the orbit-determination uncertainty changes.")
    print(f"  Predicted dilution boundary: sigma = d/sqrt(2) = {BOUNDARY:,.0f} m")
    print()

    header = f"  {'sigma (m)':>10}  {'Pc':>12}  {'Pc max':>12}  {'k*':>8}  {'verdict':>22}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    sigmas = [100.0, 300.0, 500.0, 645.5, 707.1, 1000.0, 2041.0, 5000.0]
    previous_pc = None

    for sigma in sigmas:
        result = assess(make_conjunction(MISS_M, sigma, radius_m=RADIUS_M))
        k_star = result.diagnostics["k_star"]

        if result.dilution_flag:
            verdict = "DILUTED - Pc unreliable"
        else:
            verdict = "bounded above"

        arrow = " "
        if previous_pc is not None:
            arrow = "v" if result.pc < previous_pc else "^"
        previous_pc = result.pc

        print(
            f"  {sigma:>10,.0f}  {result.pc:>12.3e}{arrow} {result.pc_max:>12.3e}"
            f"  {k_star:>8.3f}  {verdict:>22}"
        )

    print()
    print("  Read the Pc column top to bottom. It rises, peaks, then falls.")
    print("  Every row below the peak reports a LOWER collision probability")
    print("  than the row above it, while knowing strictly less about where")
    print("  the objects actually are.")
    print()
    print("  Pc max does not move. The worst case over covariance scaling is")
    print("  a property of the geometry, not of how well anyone measured it.")
    print()


if __name__ == "__main__":
    main()
