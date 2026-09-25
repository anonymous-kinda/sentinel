"""A monotonic clock a test moves by hand, for LinkMonitor(clock=...)."""

from __future__ import annotations


class ManualClock:
    """Seconds, as time.monotonic() counts them, that pass only when told to."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
