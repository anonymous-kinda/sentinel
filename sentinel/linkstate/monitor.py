"""Classify the link to the hub from what the sync agent actually observes.

    CONNECTED   exchanges succeed, round trip < 1 s, throughput adequate
    DEGRADED    exchanges succeed but slowly (round trip >= 1 s) or flakily
    LIMITED     exchanges succeed but throughput < 4 kB/s
    DENIED      no successful exchange within the grace period

The state is measured, never configured: an operator reads what the link
is doing, and the AI tier policy (M5) and the sync agent's admission
control act on that measurement - not on a flag somebody forgot to reset.
"""

from __future__ import annotations

import dataclasses
import enum
import time
from typing import Any


class LinkState(enum.StrEnum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    LIMITED = "LIMITED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"


@dataclasses.dataclass
class LinkMonitor:
    denied_after_s: float = 8.0
    slow_rtt_s: float = 1.0
    limited_bytes_per_s: float = 4000.0
    alpha: float = 0.3

    rtt_s: float | None = None
    rate_bytes_per_s: float | None = None
    last_success: float | None = None
    last_failure: float | None = None
    failures_in_row: int = 0
    bytes_total: int = 0
    exchanges: int = 0

    def observe_success(self, rtt_s: float, nbytes: int = 0, duration_s: float | None = None) -> None:
        now = time.monotonic()
        if self.state == LinkState.DENIED:
            # A link that comes back after a denial is a new link: forget the
            # old averages, or a thin reconnect would read as the fast link
            # that went away.
            self.rtt_s = None
            self.rate_bytes_per_s = None
        self.rtt_s = rtt_s if self.rtt_s is None else self.alpha * rtt_s + (1 - self.alpha) * self.rtt_s
        # Throughput is only meaningful for transfers big enough to fill the pipe.
        if nbytes >= 2000 and duration_s and duration_s > 0:
            rate = nbytes / duration_s
            self.rate_bytes_per_s = (
                rate if self.rate_bytes_per_s is None else self.alpha * rate + (1 - self.alpha) * self.rate_bytes_per_s
            )
        self.last_success = now
        self.failures_in_row = 0
        self.bytes_total += nbytes
        self.exchanges += 1

    def observe_failure(self) -> None:
        self.last_failure = time.monotonic()
        self.failures_in_row += 1

    @property
    def state(self) -> LinkState:
        now = time.monotonic()
        if self.last_success is None:
            return LinkState.DENIED if self.failures_in_row else LinkState.UNKNOWN
        if now - self.last_success > self.denied_after_s and self.failures_in_row > 0:
            return LinkState.DENIED
        if self.rate_bytes_per_s is not None and self.rate_bytes_per_s < self.limited_bytes_per_s:
            return LinkState.LIMITED
        if (self.rtt_s or 0) >= self.slow_rtt_s or self.failures_in_row > 0:
            return LinkState.DEGRADED
        return LinkState.CONNECTED

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        return {
            "state": self.state.value,
            "rtt_ms": None if self.rtt_s is None else round(self.rtt_s * 1000, 1),
            "rate_bytes_per_s": None if self.rate_bytes_per_s is None else round(self.rate_bytes_per_s),
            "seconds_since_success": None if self.last_success is None else round(now - self.last_success, 1),
            "failures_in_row": self.failures_in_row,
            "bytes_total": self.bytes_total,
            "exchanges": self.exchanges,
        }

    def eta_s(self, nbytes: int) -> float | None:
        """Estimated seconds to move nbytes at the measured rate."""
        if self.rate_bytes_per_s:
            return nbytes / self.rate_bytes_per_s + (self.rtt_s or 0)
        return None
