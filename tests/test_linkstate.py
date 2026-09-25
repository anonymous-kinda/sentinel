"""The link state is measured, and follows the link in both directions.

The exchanges below are the ones the sync agent reports each cycle (an
operator-data exchange, a manifest check that comes back unchanged, and a
record when one is queued), with the durations each Toxiproxy preset the
DDIL harness uses gives them. The monitor's clock is a hand-moved one, so
every step is exact.
"""

from __future__ import annotations

import pytest

from sentinel.linkstate import LinkMonitor, LinkState
from tests.linkclock import ManualClock

# One-way latency (s), its jitter (s) and bandwidth (B/s): sentinel/linkstate/toxiproxy.py
PRESETS = {
    "CONNECTED": (0.001, 0.0, 10_000_000),
    "DEGRADED": (0.6, 0.2, 32_000),
    "LIMITED": (0.6, 0.1, 1_000),
}
JITTER = (0.0, 0.7, -0.4, 1.0, -1.0, 0.3, -0.8, 0.5)   # a fraction of the preset's jitter, in turn
OPS_BYTES = 260            # an operator-data exchange with nothing to carry, both ways
UNCHANGED_BYTES = 0        # a manifest check the hub answers "unchanged"
RECORD_BYTES = 5_000       # one CDM
INTERVAL_S = 2.0


class Link:
    """Replays the agent's exchanges over one preset into a monitor."""

    def __init__(self, monitor: LinkMonitor, clock: ManualClock):
        self.monitor, self.clock, self.turn = monitor, clock, 0

    def exchange(self, preset: str, nbytes: int) -> None:
        latency, jitter, rate = PRESETS[preset]
        seconds = 2 * (latency + jitter * JITTER[self.turn % len(JITTER)]) + nbytes / rate
        self.turn += 1
        self.clock.advance(seconds)
        self.monitor.observe_success(seconds, nbytes, seconds)

    def cycles(self, preset: str, count: int, records: int = 0) -> list[LinkState]:
        """`count` sync cycles; the state read after each."""
        states = []
        for _ in range(count):
            for nbytes in (OPS_BYTES, UNCHANGED_BYTES, *[RECORD_BYTES] * records):
                self.exchange(preset, nbytes)
            states.append(self.monitor.state)
            self.clock.advance(INTERVAL_S)
        return states


@pytest.fixture
def link() -> Link:
    clock = ManualClock()
    return Link(LinkMonitor(clock=clock), clock)


def test_a_thin_link_reads_limited_while_records_cross(link):
    states = link.cycles("LIMITED", 30, records=1)
    assert set(states) == {LinkState.LIMITED}


def test_limited_back_to_connected_reads_connected_within_a_cycle(link):
    """The rate used to update only on transfers of 2 kB or more, and the
    averages reset only after DENIED: an idle link that came back fast kept
    reading LIMITED, which also kept Claude out of the AI tier."""
    link.cycles("LIMITED", 5, records=1)
    assert link.cycles("CONNECTED", 1) == [LinkState.CONNECTED]


def test_limited_to_degraded_while_idle_stops_reading_limited_within_the_rate_age(link):
    """Nothing that moves throughput crosses an idle link, and a small
    exchange cannot tell latency from bandwidth. So a throughput measured
    longer ago than rate_max_age_s no longer makes the link LIMITED: the
    state then rests on what is measured, the round trip."""
    link.cycles("LIMITED", 5, records=1)
    cycle_s = INTERVAL_S + 2 * 2 * PRESETS["DEGRADED"][0]
    states = link.cycles("DEGRADED", int(link.monitor.rate_max_age_s / cycle_s) + 2)
    assert states[-1] is LinkState.DEGRADED


def test_a_thin_idle_link_keeps_its_measurement_for_the_rate_age(link):
    link.cycles("LIMITED", 5, records=1)
    cycle_s = INTERVAL_S + 2 * 2 * PRESETS["LIMITED"][0]
    states = link.cycles("LIMITED", int(link.monitor.rate_max_age_s / cycle_s) - 2)
    assert set(states) == {LinkState.LIMITED}


def test_connected_to_limited_forgets_the_fast_rate_within_a_cycle(link):
    """A sudden fast-to-thin change: requests were sized from the fast rate,
    so records and manifests timed out on the thin link. The round trip
    grows first, on every exchange; once it has grown far past the one the
    rate was measured with, the rate describes another link."""
    link.cycles("CONNECTED", 5, records=1)
    fast = link.monitor.rate_bytes_per_s
    link.cycles("LIMITED", 1)
    assert link.monitor.rate_bytes_per_s is None or link.monitor.rate_bytes_per_s < fast / 100
    assert link.cycles("LIMITED", 1, records=1) == [LinkState.LIMITED]


def test_one_slow_round_trip_neither_decides_the_state_nor_forgets_the_rate(link):
    link.cycles("CONNECTED", 5, records=1)
    rate = link.monitor.rate_bytes_per_s
    link.monitor.observe_success(1.5)
    assert link.monitor.state is LinkState.CONNECTED
    assert link.monitor.rate_bytes_per_s == rate


def test_a_small_exchange_faster_than_the_rate_raises_it():
    """A transfer of n bytes in d seconds proves the link moves at least n/d."""
    clock = ManualClock()
    m = LinkMonitor(clock=clock, rate_bytes_per_s=1_000.0)
    m.observe_success(0.01, 500, 0.01)
    assert m.rate_bytes_per_s == 50_000.0
    m.observe_success(1.0, 500, 1.0)
    assert m.rate_bytes_per_s == 50_000.0, "a slow small exchange proves nothing about throughput"


def test_states_follow_measurements():
    clock = ManualClock()
    m = LinkMonitor(denied_after_s=8.0, clock=clock)
    assert m.state is LinkState.UNKNOWN
    m.observe_success(0.01)
    m.observe_success(0.01, 50_000, 0.01)
    assert m.state is LinkState.CONNECTED
    m.observe_success(1.5)
    assert m.state is LinkState.CONNECTED, "one slow round trip is smoothed, not a verdict"
    for _ in range(4):
        m.observe_success(1.5)
    assert m.state is LinkState.DEGRADED
    m.observe_failure()
    clock.advance(8.1)
    m.observe_failure()
    assert m.state is LinkState.DENIED


def test_one_lost_request_is_not_a_denial_however_long_it_waited():
    """Every request waits at least 6 s and the next cycle starts 2 s after
    a loss, so one lost request always ran past the 8 s grace: any single
    timeout, on any link, read DENIED until the next exchange."""
    clock = ManualClock()
    m = LinkMonitor(denied_after_s=8.0, clock=clock)
    m.observe_success(0.01)
    clock.advance(6.0)
    m.observe_failure()
    clock.advance(30.0)
    assert m.state is LinkState.DEGRADED
    m.observe_failure()
    assert m.state is LinkState.DENIED


def test_recovery_forgets_the_fast_link_that_went_away():
    clock = ManualClock()
    m = LinkMonitor(denied_after_s=8.0, clock=clock)
    m.observe_success(0.002, 5_000_000, 1.0)          # fast LAN-class link
    m.observe_failure()
    clock.advance(8.1)
    m.observe_failure()
    assert m.state is LinkState.DENIED
    m.observe_success(6.0, 6_000, 6.0)                # back, over a thin link
    assert m.rate_bytes_per_s == 1000.0
    assert m.state is LinkState.LIMITED


def test_eta_uses_measured_rate():
    m = LinkMonitor(clock=ManualClock())
    assert m.eta_s(10_000) is None
    m.observe_success(0.5)
    m.observe_success(4.0, 4_000, 4.0)
    assert round(m.eta_s(10_000), 1) == 10.5
