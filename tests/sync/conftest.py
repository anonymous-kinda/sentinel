"""Hub and edge in one process over a shared in-process bus: the scenario
every sync test starts from (the exercise CDMs released one minute in)."""

import asyncio
import datetime as dt

import pytest

from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock
from sentinel.conjunction.exercise import generate
from sentinel.conjunction.service import ConjunctionService
from sentinel.conjunction.store import ConjunctionStore
from sentinel.conjunction.sync_adapter import ConjunctionRecords
from sentinel.crdt import NodeKey, TrustStore
from sentinel.linkstate import LinkMonitor
from sentinel.ops import OpsService
from sentinel.sync import SyncAgent, SyncServer

EPOCH = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.UTC)
KEYS = {n: NodeKey.generate(n) for n in ("hub", "alpha")}
TRUST = {n: k.public_hex() for n, k in KEYS.items()}


class Node:
    def __init__(self, node_id: str, bus: InProcessBus, clock: FixedClock):
        self.id = node_id
        self.conj = ConjunctionService(ConjunctionStore(), bus, clock, node_id=node_id)
        self.ops = OpsService(node_id, KEYS[node_id], TrustStore(TRUST), bus, clock, current_ref=self.conj.current_ref)
        self.records = ConjunctionRecords(self.conj)


@pytest.fixture
def pair():
    bus = InProcessBus()
    clock = FixedClock(EPOCH + dt.timedelta(minutes=1))  # later scripted updates still pending
    hub, edge = Node("hub", bus, clock), Node("alpha", bus, clock)

    async def setup():
        await SyncServer(bus, hub.records, hub.ops, "hub").start()
        for item in generate(EPOCH):
            if item.release_at <= clock.now():
                await hub.conj.ingest(item.kvn.encode(), "exercise", "EXERCISE")

    asyncio.run(setup())
    agent = SyncAgent(bus, edge.records, edge.ops, clock, "alpha", "hub", LinkMonitor())
    return hub, edge, agent, clock


def run(coro):
    return asyncio.run(coro)
