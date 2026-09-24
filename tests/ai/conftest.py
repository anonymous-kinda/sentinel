"""A real edge node's services, loaded with the exercise scenario.

The assistant is tested against the same services the API serves - not
against hand-written facts that could drift from what the tools return.
"""

import asyncio
import datetime as dt

import pytest

from sentinel.ai.tools import ToolRegistry
from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock
from sentinel.conjunction.exercise import generate
from sentinel.conjunction.service import ConjunctionService
from sentinel.conjunction.store import ConjunctionStore
from sentinel.crdt import NodeKey, TrustStore
from sentinel.linkstate import LinkMonitor
from sentinel.ops import OpsService

EPOCH = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.UTC)
QUEUE = {"queue": [{"event_id": "E1", "class": "P1_URGENT", "bytes": 2961, "eta_s": 1.4}], "summary_only": []}


NOW = EPOCH + dt.timedelta(hours=1)


def build_registry(at: dt.datetime = NOW) -> ToolRegistry:
    """Every exercise CDM released by `at`, ingested and assessed."""
    clock = FixedClock(at)
    bus = InProcessBus()
    conj = ConjunctionService(ConjunctionStore(), bus, clock, node_id="edge")
    for item in generate(EPOCH):
        if item.release_at <= clock.now():
            asyncio.run(conj.ingest(item.kvn.encode(), "exercise", "EXERCISE"))
    key = NodeKey.generate("edge")
    ops = OpsService("edge", key, TrustStore({"edge": key.public_hex()}), bus, clock, current_ref=conj.current_ref)
    link = LinkMonitor()
    link.observe_success(0.9, 6000, 3.0)
    return ToolRegistry(conj, ops, link, sync_status=lambda: QUEUE)


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    return build_registry()


@pytest.fixture(scope="module")
def event_of(registry):
    """Event id by the secondary object's catalog number."""
    events = registry.execute("list_events", {})["events"]
    return lambda secondary_id: next(e["event_id"] for e in events if e["secondary_id"] == secondary_id)
