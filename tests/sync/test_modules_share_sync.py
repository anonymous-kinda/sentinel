"""Two mission modules over one unmodified sync layer (MOSA).

Conjunction CDMs and public element sets travel through the same
SyncServer and SyncAgent. A composite routes records by item id, outside
sync, so adding the pass module changed no line in sentinel/sync.
"""

import asyncio
import datetime as dt
import pathlib

import pytest

from sentinel.api.records import CompositeRecords
from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock
from sentinel.conjunction.exercise import generate
from sentinel.conjunction.service import ConjunctionService
from sentinel.conjunction.store import ConjunctionStore
from sentinel.conjunction.sync_adapter import ConjunctionRecords
from sentinel.crdt import NodeKey, TrustStore
from sentinel.linkstate import LinkMonitor
from sentinel.ops import OpsService
from sentinel.passes.element_store import ElementStore
from sentinel.passes.sync_adapter import ElementRecords
from sentinel.sync import SyncAgent, SyncServer
from sentinel.triage import PriorityClass

SNAPSHOT = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "omm" / "celestrak-resource-20260924.json"
EPOCH = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
KEYS = {n: NodeKey.generate(n) for n in ("hub", "alpha")}
TRUST = {n: k.public_hex() for n, k in KEYS.items()}


class Node:
    def __init__(self, node_id, bus, clock):
        self.conj = ConjunctionService(ConjunctionStore(), bus, clock, node_id=node_id)
        self.ops = OpsService(node_id, KEYS[node_id], TrustStore(TRUST), bus, clock, current_ref=self.conj.current_ref)
        self.elements = ElementStore()
        self.records = CompositeRecords(ConjunctionRecords(self.conj), {"omm:": ElementRecords(self.elements, clock)})


@pytest.fixture
def synced():
    bus, clock = InProcessBus(), FixedClock(EPOCH + dt.timedelta(hours=1))
    hub, edge = Node("hub", bus, clock), Node("alpha", bus, clock)

    async def scenario():
        await SyncServer(bus, hub.records, hub.ops, "hub").start()
        for item in generate(EPOCH):
            if item.release_at <= clock.now():
                await hub.conj.ingest(item.kvn.encode(), "exercise", "EXERCISE")
        hub.elements.load_snapshot(SNAPSHOT, "celestrak")
        agent = SyncAgent(bus, edge.records, edge.ops, clock, "alpha", "hub", LinkMonitor())
        agent.apply_manifest(await agent.fetch_manifest())
        order = [(item.event_id, item.key.klass) for item in agent.queue]
        await agent.pull()
        return agent, order

    agent, order = asyncio.run(scenario())
    return hub, edge, agent, order


def test_both_modules_arrive_intact_through_one_unmodified_agent(synced):
    hub, edge, agent, _ = synced
    assert edge.elements.latest() == hub.elements.latest()
    assert {e["event_id"] for e in edge.conj.list_events()} == {e["event_id"] for e in hub.conj.list_events()}
    assert all(a["hash_ok"] for a in agent.arrivals)


def test_urgent_cdms_are_pulled_before_routine_element_sets(synced):
    *_, order = synced
    urgent = [i for i, (item, klass) in enumerate(order) if klass == PriorityClass.P1_URGENT]
    elements = [i for i, (item, _) in enumerate(order) if item.startswith("omm:")]
    assert urgent and elements, "the scenario has both"
    assert max(urgent) < min(elements), "every urgent CDM is queued ahead of every element set"


def test_element_summaries_never_leak_into_the_conjunction_view(synced):
    _, edge, *_ = synced
    assert not any(e["event_id"].startswith("omm:") for e in edge.conj.list_events("all"))
