"""The one place Sentinel asks what time it is.

Every countdown, deadline and priority depends on "now". Reading the wall
clock directly would make those untestable and would make the DDIL harness
unable to compress a six-hour denial into a minute. So everything takes a
Clock, and the process picks one from SENTINEL_CLOCK:

    real                         wall clock (default)
    sim:<ISO-8601 epoch>,<scale> starts at epoch, runs <scale>x wall speed
    fixed:<ISO-8601 instant>     frozen (tests)

A simulated clock is always labelled as such wherever its time is shown.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from typing import Protocol


class Clock(Protocol):
    label: str

    def now(self) -> dt.datetime: ...


class RealClock:
    label = "real"

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.UTC)


class FixedClock:
    def __init__(self, instant: dt.datetime):
        if instant.tzinfo is None:
            raise ValueError("FixedClock needs an aware datetime")
        self._instant = instant
        self.label = f"fixed:{instant.isoformat()}"

    def now(self) -> dt.datetime:
        return self._instant

    def advance(self, seconds: float) -> None:
        self._instant += dt.timedelta(seconds=seconds)


class SimClock:
    """Starts at `epoch` and runs `scale` times faster than wall time."""

    def __init__(self, epoch: dt.datetime, scale: float = 1.0):
        if epoch.tzinfo is None:
            raise ValueError("SimClock needs an aware epoch")
        self._epoch = epoch
        self._scale = float(scale)
        self._start = time.monotonic()
        self.label = f"sim:{epoch.isoformat()},{scale:g}x"

    def now(self) -> dt.datetime:
        elapsed = (time.monotonic() - self._start) * self._scale
        return self._epoch + dt.timedelta(seconds=elapsed)


def _parse_instant(text: str) -> dt.datetime:
    if text == "now":
        return dt.datetime.now(dt.UTC)
    value = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def from_spec(spec: str | None) -> Clock:
    spec = (spec or "real").strip()
    if spec == "real":
        return RealClock()
    kind, _, rest = spec.partition(":")
    if kind == "fixed":
        return FixedClock(_parse_instant(rest))
    if kind == "sim":
        epoch, _, scale = rest.partition(",")
        return SimClock(_parse_instant(epoch), float(scale or 1.0))
    raise ValueError(f"unknown clock spec {spec!r}")


def from_env() -> Clock:
    return from_spec(os.environ.get("SENTINEL_CLOCK"))
