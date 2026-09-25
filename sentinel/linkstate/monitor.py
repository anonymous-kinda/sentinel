"""Classify the link to the hub from what the sync agent actually observes.

    CONNECTED   exchanges succeed, round trip < 1 s, throughput adequate
    DEGRADED    exchanges succeed but slowly (round trip >= 1 s) or flakily
    LIMITED     exchanges succeed but throughput < 4 kB/s
    DENIED      no successful exchange within the grace period, and at
                least two requests in a row lost

The state is measured, never configured: an operator reads what the link
is doing, and the AI tier policy (M5) and the sync agent's admission
control act on that measurement - not on a flag somebody forgot to reset.

Every exchange is timed on the monitor's clock and measures one of two
things. A transfer of MIN_RATE_BYTES or more fills the pipe, so its bytes
over its duration are a throughput sample. A smaller one is a round trip.
The two are held to the link as it is now, in both directions:

  * A small exchange that moved n bytes in d seconds proves the link moves
    at least n/d, so one faster than the rate raises it.
  * A round trip that grows far past the one the rate was measured with
    means another, slower link: the rate describes the old one and is
    forgotten, so requests are sized afresh rather than timing out.
  * A throughput measured longer ago than `rate_max_age_s` no longer makes
    the link LIMITED. An idle link moves nothing that measures throughput,
    and a small exchange cannot tell latency from bandwidth, so the state
    then rests on the round trip, which every exchange measures.
  * After a denial every average is forgotten: a link that comes back is a
    new link.

One lost request is not a denial. Every request waits at least 6 s and the
next cycle starts after the interval, so a single loss always runs past the
grace period; a denial is the second loss in a row with no success between.
"""

from __future__ import annotations

import dataclasses
import enum
import time
from collections.abc import Callable
from typing import Any

MIN_RATE_BYTES = 2000       # a transfer this large measures throughput; a smaller one, the round trip
NEW_LINK_FACTOR = 4.0       # a round trip this many times the fastest since the rate was measured ...
NEW_LINK_MIN_S = 0.5        # ... and this much longer is another link, not jitter


class LinkState(enum.StrEnum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    LIMITED = "LIMITED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"


@dataclasses.dataclass
class LinkMonitor:
    denied_after_s: float = 8.0
    denied_after_losses: int = 2
    slow_rtt_s: float = 1.0
    limited_bytes_per_s: float = 4000.0
    alpha: float = 0.3
    rate_max_age_s: float = 60.0
    clock: Callable[[], float] = dataclasses.field(default=time.monotonic, repr=False)

    rtt_s: float | None = None
    rate_bytes_per_s: float | None = None
    rate_measured_at: float | None = None
    rate_rtt_s: float | None = None     # the fastest round trip since the rate was measured
    last_success: float | None = None
    last_failure: float | None = None
    failures_in_row: int = 0
    bytes_total: int = 0
    exchanges: int = 0

    def observe_success(self, rtt_s: float, nbytes: int = 0, duration_s: float | None = None) -> None:
        now = self.clock()
        if self.state == LinkState.DENIED:
            # A link that comes back after a denial is a new link: forget the
            # old averages, or a thin reconnect would read as the fast link
            # that went away.
            self.rtt_s = None
            self._forget_rate()
        if nbytes >= MIN_RATE_BYTES:
            if duration_s and duration_s > 0:
                self._observe_rate(nbytes / duration_s, now)
        else:
            self._observe_round_trip(rtt_s)
            if duration_s and duration_s > 0:
                self._observe_lower_bound(nbytes / duration_s, now)
        self.last_success = now
        self.failures_in_row = 0
        self.bytes_total += nbytes
        self.exchanges += 1

    def observe_failure(self) -> None:
        self.last_failure = self.clock()
        self.failures_in_row += 1

    def _smoothed(self, previous: float | None, sample: float) -> float:
        return sample if previous is None else self.alpha * sample + (1 - self.alpha) * previous

    def _observe_rate(self, rate: float, now: float) -> None:
        self.rate_bytes_per_s = self._smoothed(self.rate_bytes_per_s, rate)
        self.rate_measured_at = now
        self.rate_rtt_s = self.rtt_s

    def _observe_lower_bound(self, rate: float, now: float) -> None:
        if self.rate_bytes_per_s is not None and rate > self.rate_bytes_per_s:
            self.rate_bytes_per_s = rate
            self.rate_measured_at = now

    def _observe_round_trip(self, rtt_s: float) -> None:
        self.rtt_s = self._smoothed(self.rtt_s, rtt_s)
        if self.rate_bytes_per_s is None:
            return
        base = self.rtt_s if self.rate_rtt_s is None else min(self.rate_rtt_s, self.rtt_s)
        if self.rtt_s > NEW_LINK_FACTOR * base and self.rtt_s - base > NEW_LINK_MIN_S:
            self._forget_rate()
        else:
            self.rate_rtt_s = base

    def _forget_rate(self) -> None:
        self.rate_bytes_per_s = None
        self.rate_measured_at = None
        self.rate_rtt_s = None

    def _rate_is_current(self, now: float) -> bool:
        return self.rate_measured_at is not None and now - self.rate_measured_at <= self.rate_max_age_s

    @property
    def state(self) -> LinkState:
        now = self.clock()
        if self.last_success is None:
            return LinkState.DENIED if self.failures_in_row else LinkState.UNKNOWN
        if now - self.last_success > self.denied_after_s and self.failures_in_row >= self.denied_after_losses:
            return LinkState.DENIED
        if (
            self.rate_bytes_per_s is not None
            and self.rate_bytes_per_s < self.limited_bytes_per_s
            and self._rate_is_current(now)
        ):
            return LinkState.LIMITED
        if (self.rtt_s or 0) >= self.slow_rtt_s or self.failures_in_row > 0:
            return LinkState.DEGRADED
        return LinkState.CONNECTED

    def snapshot(self) -> dict[str, Any]:
        now = self.clock()
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
