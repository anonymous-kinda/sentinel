"""Mission-agnostic triage (ADR-006).

Every mission module reduces its items to three things the core
understands: a priority class, a deadline, and a consequence level. The
sync layer orders by those alone - it never learns what a conjunction or a
pass window is. That is what lets a new mission module plug in without
touching sync (asserted by .importlinter and by the M3 zero-diff check).

Order: class first (P0 before P4), then earliest deadline first within a
class (Liu & Layland: EDF is optimal on a single resource when a feasible
schedule exists), then higher consequence first as the tie-breaker.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum


class Consequence(enum.IntEnum):
    ROUTINE = 0
    WATCH = 1
    SERIOUS = 2
    CRITICAL = 3


class PriorityClass(enum.IntEnum):
    P0_SUMMARY = 0      # summaries, operator deltas - always first
    P1_URGENT = 1       # full records for items that need action soon
    P2_ROUTINE = 2      # other full records
    P3_REFERENCE = 3    # catalog refresh
    P4_BULK = 4         # history, only when idle


@dataclasses.dataclass(frozen=True)
class TriageKey:
    item_id: str
    klass: PriorityClass
    deadline: dt.datetime | None
    consequence: Consequence

    def sort_key(self) -> tuple:
        far_future = dt.datetime.max.replace(tzinfo=dt.UTC)
        return (int(self.klass), self.deadline or far_future, -int(self.consequence), self.item_id)


def order(items: list[TriageKey]) -> list[TriageKey]:
    return sorted(items, key=TriageKey.sort_key)
