"""Time arguments the pass module accepts: timezone-aware, and an interval
that ends after it starts. A naive datetime would be read in whatever zone
the host runs in, which makes every pass time wrong, so it raises."""

from __future__ import annotations

import datetime as dt


def require_aware(when: dt.datetime, name: str) -> None:
    if when.tzinfo is None:
        raise ValueError(f"{name} needs a timezone-aware datetime")


def require_interval(start: dt.datetime, end: dt.datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("pass interval needs timezone-aware datetimes")
    if end <= start:
        raise ValueError("pass interval must end after it starts")
