"""Operator data over a thin link: a backlog reaches the edge.

After a long partition the hub holds operator entries the edge has never
seen. Sent whole in one reply, that backlog outran the edge's wait on a
thin link, was lost, and the next cycle asked for exactly the same thing.
Each exchange now carries a budget each way, what the measured link moves
in 10 s, so the backlog drains over a few cycles and the wait covers it.
"""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from sentinel.bus import subjects
from sentinel.clock import FixedClock
from sentinel.crdt import DotContext, NodeKey, TrustStore, codec
from sentinel.linkstate import LinkMonitor
from sentinel.ops import OpsService
from sentinel.sync import SyncAgent, SyncServer
from sentinel.sync.agent import LINK_ERRORS
from tests.sync.test_hostile_hub import ThinLinkBus

NOW = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.UTC)
KEYS = {n: NodeKey.generate(n) for n in ("hub", "alpha", "bravo")}
TRUST = {n: k.public_hex() for n, k in KEYS.items()}
RATE = 1000.0                                   # ~8 kbit/s: the LIMITED scenario


def run(coro):
    return asyncio.run(coro)


def replica(node: str, bus: ThinLinkBus) -> OpsService:
    return OpsService(node, KEYS[node], TrustStore(TRUST), bus, FixedClock(NOW))


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
        agent.link.rate_bytes_per_s = RATE      # what a monitor on this link measures; the bus is instant
        try:
            run(agent.exchange_ops())
        except LINK_ERRORS:
            agent.link.observe_failure()
    assert len(edge.log.entries) == 60, "the edge never received the hub's backlog"


# ------------------------------------------------------ a budget per exchange
NOTHING = DotContext().to_wire()


def written(node: str, bus: ThinLinkBus, entries: int, annotations: int) -> OpsService:
    """A replica holding what it wrote through a partition."""
    ops = replica(node, bus)
    for n in range(entries):
        run(ops.append(f"EVENT-{n % 12:03d}", "NOTE", {"text": f"{node} item {n}: " + "x" * 80}, f"op@{node}"))
    for n in range(annotations):
        run(ops.annotate(f"EVENT-{n:03d}", "note", f"{node} says {n}", f"op@{node}"))
    return ops


def item_sizes(payload: dict) -> list[int]:
    return [len(codec.encode(e)) for e in payload["log"]] + [
        len(codec.encode([k, r])) for k, r in payload["reg"].items()
    ]


def test_a_budgeted_payload_is_the_oldest_first_prefix_that_fits():
    hub = written("hub", ThinLinkBus(RATE), entries=30, annotations=10)
    everything = hub.payload_for(NOTHING, NOTHING)
    part = hub.payload_for(NOTHING, NOTHING, budget_bytes=4000)
    oldest_first = sorted(everything["log"], key=lambda e: (e["lamport"], e["dot"]))
    assert part["log"] == oldest_first[: len(part["log"])]
    assert 0 < len(part["log"]) < len(everything["log"])
    assert sum(item_sizes(part)) <= 4000


def test_a_budget_smaller_than_one_item_still_sends_one():
    """Every exchange makes progress, however thin the budget."""
    hub = written("hub", ThinLinkBus(RATE), entries=3, annotations=0)
    assert len(hub.payload_for(NOTHING, NOTHING, budget_bytes=1)["log"]) == 1


class MeasuredLink(ThinLinkBus):
    """A thin link that records the bytes of every exchange each way."""

    def __init__(self, rate_bytes_per_s: float):
        super().__init__(rate_bytes_per_s)
        self.exchanges: list[tuple[int, int]] = []

    async def request(self, subject, data, timeout, headers=None):
        reply = await super().request(subject, data, timeout, headers)
        self.exchanges.append((len(data), len(reply.data)))
        return reply


def test_each_exchange_spends_a_bounded_share_of_the_link_and_both_backlogs_converge():
    """Both sides wrote through a partition. Each exchange carries at most its
    budget of operator data each way, so the manifest and records behind it
    still get the link every cycle, and a few exchanges bring both replicas
    to the same state: the part not yet sent is never lost."""
    bus = MeasuredLink(RATE)
    hub = written("hub", bus, entries=60, annotations=20)
    run(SyncServer(bus, None, hub, "hub").start())
    edge = written("alpha", bus, entries=60, annotations=20)
    agent = SyncAgent(bus, None, edge, FixedClock(NOW), "alpha", "hub", LinkMonitor(rate_bytes_per_s=RATE))

    for _ in range(12):
        agent.link.rate_bytes_per_s = RATE
        run(agent.exchange_ops())
    budget = RATE * 10
    assert all(sent <= budget + 2000 and got <= budget + 2000 for sent, got in bus.exchanges), bus.exchanges
    assert hub.digest()["log"] == edge.digest()["log"] and len(edge.log.entries) == 120
    assert hub.digest()["annotations"] == edge.digest()["annotations"]


def test_entries_a_peer_rejects_do_not_starve_the_ones_it_accepts():
    """A rejected entry never enters the peer's context, so it is offered
    again on every exchange (sentinel/crdt/log.py). Offered oldest first,
    the rejected ones filled the budget before anything else: with the hub
    trusting bravo and alpha not, 60 bravo notes kept the hub's own 5 from
    alpha for good at 400 B/s."""
    bus = ThinLinkBus(400.0)
    hub = replica("hub", bus)
    bravo = replica("bravo", bus)
    for n in range(60):
        run(bravo.append(f"EVENT-{n % 12:03d}", "NOTE", {"text": f"bravo item {n}: " + "x" * 80}, "op@bravo"))
    run(hub.merge_payload(bravo.payload_for(**hub.contexts())))
    for n in range(5):
        run(hub.append("EVENT-000", "NOTE", {"text": f"hub item {n}"}, "capt.lee@hub"))
    run(SyncServer(bus, None, hub, "hub").start())
    alpha = OpsService("alpha", KEYS["alpha"], TrustStore({n: TRUST[n] for n in ("hub", "alpha")}), bus, FixedClock(NOW))
    agent = SyncAgent(bus, None, alpha, FixedClock(NOW), "alpha", "hub",
                      LinkMonitor(rate_bytes_per_s=400.0, clock=bus.clock))

    for _ in range(20):
        run(agent.exchange_ops())
    from_hub = {dot for dot in hub.log.entries if dot.node == "hub"}
    assert from_hub <= set(alpha.log.entries), f"{len(from_hub - set(alpha.log.entries))} of the hub's 5 never arrived"


@pytest.mark.parametrize("budget", [0, -1, "10000", True, 2.5, None])
def test_a_budget_the_hub_cannot_read_gets_everything_not_an_error(budget):
    """An edge that sends no budget, or one that is not a positive integer,
    is answered as before the budget existed: with everything it lacks."""
    bus = ThinLinkBus(10**9)
    hub = written("hub", bus, entries=30, annotations=0)
    run(SyncServer(bus, None, hub, "hub").start())
    request = {"from": "alpha", "log_ctx": NOTHING, "mv_ctx": NOTHING, "push": {"log": [], "reg": {}}}
    if budget is not None:
        request["budget"] = budget
    reply = run(bus.request(subjects.ops_exchange("hub"), codec.encode(request), 5.0))
    assert len(codec.decode(reply.data)["pull"]["log"]) == 30
