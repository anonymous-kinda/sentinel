"""Gaps: when no catalogued imager can observe the unit.

A gap is time inside [start, end] that no *usable, padded* window covers.
Usable means a SAR pass, or an optical pass with the unit in daylight.
Padded means widened by the element-set timing pad (PassWindow.padded), so
element-set error shrinks a gap rather than growing it.

A gap is not an all-clear. It means only that no imager in the catalog,
under its planning assumptions and these element sets, has the unit in its
field of regard. Uncatalogued or newly launched imagers, aircraft and
ground sensors are not counted. GAP_LABEL says exactly that and no more.

A gap is low confidence when any window that bounds it or overlaps it came
from a stale element set, because its edges may then be off by more than
the pad. A gap that reaches `end` is cut there, and may run on.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Iterable, Iterator

from .interval import require_aware, require_interval
from .model import PassWindow

GAP_LABEL = "not observed by catalogued imagers"

Span = tuple[dt.datetime, dt.datetime]


@dataclasses.dataclass(frozen=True)
class Gap:
    start: dt.datetime
    end: dt.datetime
    low_confidence: bool
    label: str = GAP_LABEL

    @property
    def duration_s(self) -> float:
        return (self.end - self.start).total_seconds()


def unobserved_gaps(windows: Iterable[PassWindow], start: dt.datetime, end: dt.datetime) -> list[Gap]:
    require_interval(start, end)
    windows = list(windows)
    observed = _merge(w.padded for w in windows if w.usable)
    stale = [w.padded for w in windows if w.stale]
    return [Gap(a, b, low_confidence=_touches_any((a, b), stale)) for a, b in _complement(observed, start, end)]


def next_unobserved(gaps: Iterable[Gap], now: dt.datetime, min_duration: dt.timedelta) -> Gap | None:
    """The first gap with at least `min_duration` (the unit's reaction time)
    still to run after `now`. A gap already in progress counts from `now`,
    and is returned starting there."""
    require_aware(now, "now")
    if min_duration < dt.timedelta(0):
        raise ValueError("min_duration must not be negative")
    for gap in sorted(gaps, key=lambda g: g.start):
        begins = max(gap.start, now)
        if gap.end > now and gap.end - begins >= min_duration:
            return dataclasses.replace(gap, start=begins)
    return None


def _merge(spans: Iterable[Span]) -> list[Span]:
    merged: list[Span] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _complement(observed: list[Span], start: dt.datetime, end: dt.datetime) -> Iterator[Span]:
    cursor = start
    for a, b in observed:
        if min(a, end) > cursor:
            yield cursor, min(a, end)
        cursor = max(cursor, b)
        if cursor >= end:
            return
    yield cursor, end


def _touches_any(span: Span, others: list[Span]) -> bool:
    a, b = span
    return any(x <= b and y >= a for x, y in others)
