"""Operator data over a thin link: a backlog reaches the edge.

After a long partition the hub holds operator entries the edge has never
seen, and the whole backlog comes back in one exchange reply. The edge's
request has to wait long enough for that reply to cross the measured link,
or it is lost, and the next cycle asks for exactly the same thing.

Bugs in the closed core (sentinel/sync) are strict xfails.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from sentinel.clock import FixedClock
from sentinel.crdt import DotContext, NodeKey, TrustStore, codec
from sentinel.linkstate import LinkMonitor
from sentinel.ops import OpsService
from sentinel.sync import SyncAgent, SyncServer
from sentinel.sync.agent import LINK_ERRORS
from tests.sync.test_hostile_hub import ThinLinkBus

NOW = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.UTC)
KEYS = {n: NodeKey.generate(n) for n in ("hub", "alpha")}
TRUST = {n: k.public_hex() for n, k in KEYS.items()}
RATE = 1000.0                                   # ~8 kbit/s: the LIMITED scenario
CORE = "core bug in sentinel/sync (closed; fix belongs to its owner): "


def run(coro):
    return asyncio.run(coro)


def replica(node: str, bus: ThinLinkBus) -> OpsService:
    return OpsService(node, KEYS[node], TrustStore(TRUST), bus, FixedClock(NOW))


@pytest.mark.xfail(strict=True, reason=CORE + (
    "SyncAgent.exchange_ops sizes its timeout from the request (_timeout(len(request) + 2000)), "
    "but the reply carries the hub's whole backlog: 60 entries are a 26 kB reply that needs 26 s "
    "at 1000 B/s, and the agent waits 9 s, every cycle, identically, forever. The exchange runs "
    "first in cycle(), so the manifest and CDM fetch never run either"))
def test_a_backlog_of_operator_entries_reaches_the_edge_on_a_limited_link():
    bus = ThinLinkBus(RATE)
    hub = replica("hub", bus)
    for n in range(60):                         # decisions and notes written through a partition
        run(hub.append(f"EVENT-{n % 12:03d}", "NOTE", {"text": f"watch item {n}: " + "x" * 80}, "capt.lee@hub"))
    run(SyncServer(bus, None, hub, "hub").start())
    edge = replica("alpha", bus)
    agent = SyncAgent(bus, None, edge, FixedClock(NOW), "alpha", "hub", LinkMonitor(rate_bytes_per_s=RATE))

    backlog = len(codec.encode(hub.payload_for(DotContext().to_wire(), DotContext().to_wire())))
    assert backlog > 6 * RATE + 1.5 * 4000, "the reply needs longer than the agent waits for a small request"

    for _ in range(8):
        try:
            run(agent.exchange_ops())
        except LINK_ERRORS:
            agent.link.observe_failure()
    assert len(edge.log.entries) == 60, "the edge never received the hub's backlog"
