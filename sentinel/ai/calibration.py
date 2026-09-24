"""Is a router's confidence worth trusting? Calibration of stated confidence.

Each pair is (confidence the router stated, whether its choice was right).
A calibrated router is right about 80% of the time when it says 0.8 - the
property that makes a confidence gate (ask when below 0.5) meaningful.

    Brier  mean squared gap between confidence and outcome (0 is perfect)
    ECE    expected calibration error: per-bin |accuracy - confidence|,
           weighted by the share of cases in the bin
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

Pair = tuple[float, bool]


@dataclasses.dataclass(frozen=True)
class Bin:
    lo: float
    hi: float
    count: int
    confidence: float | None      # mean stated confidence
    accuracy: float | None        # observed fraction right


def brier(pairs: Sequence[Pair]) -> float | None:
    if not pairs:
        return None
    return sum((p - float(y)) ** 2 for p, y in pairs) / len(pairs)


def reliability(pairs: Sequence[Pair], bins: int = 10) -> list[Bin]:
    grouped: list[list[Pair]] = [[] for _ in range(bins)]
    for p, y in pairs:
        grouped[min(int(p * bins), bins - 1)].append((p, y))
    return [
        Bin(
            lo=i / bins,
            hi=(i + 1) / bins,
            count=len(group),
            confidence=sum(p for p, _ in group) / len(group) if group else None,
            accuracy=sum(y for _, y in group) / len(group) if group else None,
        )
        for i, group in enumerate(grouped)
    ]


def ece(pairs: Sequence[Pair], bins: int = 10) -> float | None:
    if not pairs:
        return None
    return sum(b.count / len(pairs) * abs(b.accuracy - b.confidence) for b in reliability(pairs, bins) if b.count)
