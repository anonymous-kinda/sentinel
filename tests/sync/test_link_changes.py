"""The edge keeps syncing, and reads the link right, when the link changes
under it: the harness presets, switched mid-run over an in-process link
whose every request spends its preset's time on the link monitor's clock."""

from __future__ import annotations

import datetime as dt

from sentinel.bus import InProcessBus, RequestTimeout
from sentinel.clock import FixedClock
from sentinel.conjunction.exercise import generate
from sentinel.linkstate import LinkMonitor, LinkState
from sentinel.sync import SyncAgent, SyncServer
from tests.linkclock import ManualClock

from .conftest import EPOCH, Node, run

PRESETS = {                     # one-way latency (s) and bandwidth (B/s): sentinel/linkstate/toxiproxy.py
    "CONNECTED": (0.001, 10_000_000),
    "LIMITED": (0.6, 1_000),
}
INTERVAL_S = 2.0


class ShapedLink(InProcessBus):
    """A request takes the preset's round trip plus its bytes at the preset's
    rate. One that needs longer than the requester waits is lost."""

    def __init__(self, clock: ManualClock):
        super().__init__()
        self.clock = clock
        self.preset = "CONNECTED"

    async def request(self, subject, data, timeout, headers=None):
        reply = await super().request(subject, data, 3600.0, headers)
        latency, rate = PRESETS[self.preset]
        seconds = 2 * latency + (len(data) + len(reply.data)) / rate
        if seconds > timeout:
            self.clock.advance(timeout)
            raise RequestTimeout(subject)
        self.clock.advance(seconds)
        return reply


def cycles(agent: SyncAgent, clock: ManualClock, count: int) -> list[LinkState]:
    """The state after each cycle, and at the end of the wait before the
    next: the console reads it at any moment."""
    states = []
    for _ in range(count):
        run(agent.step())
        states.append(agent.link.state)
        clock.advance(INTERVAL_S)
        states.append(agent.link.state)
    return states


def held(node: Node) -> set[str]:
    return {row.sha256[:16] for row in node.conj.store.all_cdms()}


def test_a_sudden_fast_to_thin_change_neither_stalls_sync_nor_reads_denied():
    """Requests were sized from the fast link's rate, so on the thin link
    every record outran its wait: the edge read the link as failing (DENIED
    once two waits ran past the grace period) and the records never came."""
    link_clock = ManualClock()
    bus = ShapedLink(link_clock)
    clock = FixedClock(EPOCH + dt.timedelta(minutes=1))
    hub, edge = Node("hub", bus, clock), Node("alpha", bus, clock)
    run(SyncServer(bus, hub.records, hub.ops, "hub").start())
    released, later = [], []
    for item in generate(EPOCH):
        (released if item.release_at <= clock.now() else later).append(item)
    for item in released:
        run(hub.conj.ingest(item.kvn.encode(), "exercise", "EXERCISE"))
    agent = SyncAgent(bus, edge.records, edge.ops, clock, "alpha", "hub", LinkMonitor(clock=link_clock))
    cycles(agent, link_clock, 3)
    assert held(edge) == held(hub) and agent.link.state is LinkState.CONNECTED

    for item in later:                              # the hub keeps receiving ...
        run(hub.conj.ingest(item.kvn.encode(), "exercise", "EXERCISE"))
    bus.preset = "LIMITED"                          # ... as the link turns thin
    states: list[LinkState] = []
    while held(edge) != held(hub) and len(states) < 2 * 40:
        states += cycles(agent, link_clock, 1)

    assert LinkState.DENIED not in states, states
    assert held(edge) == held(hub), "records stopped crossing the thin link"
    assert agent.link.state is LinkState.LIMITED, "measured as the last record crossed"
