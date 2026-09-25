"""Admission control spends a thin link on what can still arrive in time,
and withholds nothing it has room for (ADR-006, ADR-008).

A latest record that cannot arrive before its deadline at the measured rate
is held SUMMARY_ONLY while records that can still arrive in time get the
link. Once none of those is waiting, it is fetched too: an element set past
its stale time, or a CDM past its commit point, is an input the operator
still needs to see (stale inputs are shown, not hidden).
"""

from __future__ import annotations

import asyncio
import datetime as dt

from sentinel.bus import InProcessBus, Msg, subjects
from sentinel.clock import FixedClock
from sentinel.linkstate import LinkMonitor
from sentinel.sync import SyncAgent, SyncServer
from tests.linkclock import ManualClock

from .conftest import run
from .test_hostile_hub import SmallRecords, _record

NOW = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.UTC)
T0 = int(NOW.timestamp())


def hub_serving(summaries: list[dict], raws: dict[str, bytes], clock: FixedClock, link_clock: ManualClock,
                fetch_s: float = 0.0, wall_s: float = 0.0) -> InProcessBus:
    """A hub whose every fetch takes `fetch_s` of node and link time, and
    `wall_s` of real time (what a pull's budget counts)."""
    bus = InProcessBus()
    server = SyncServer(bus, SmallRecords(summaries, raws), None, "hub")
    run(server.start())

    async def fetch(msg: Msg):
        clock.advance(fetch_s)
        link_clock.advance(fetch_s)
        await asyncio.sleep(wall_s)
        return await server._fetch(msg)

    run(bus.serve(subjects.sync_fetch("hub"), fetch))
    return bus


def edge(bus: InProcessBus, clock: FixedClock, link_clock: ManualClock, rate: float, summaries: list[dict]) -> SyncAgent:
    agent = SyncAgent(bus, SmallRecords(), None, clock, "alpha", "hub",
                      LinkMonitor(rate_bytes_per_s=rate, clock=link_clock))
    agent.apply_manifest(summaries)
    return agent


def arrived(agent: SyncAgent) -> list[str]:
    return [a["event_id"] for a in agent.arrivals]


def test_admission_control_counts_the_time_spent_on_records_ahead():
    """Each fetch takes 50 s (500 B at 10 B/s, as the monitor predicts). A
    fits (50 s against 80 s). After A, B has 40 s left: it is held while C,
    which still fits, crosses, and follows once nothing in time waits."""
    clock, link_clock = FixedClock(NOW), ManualClock()
    records = {tag: _record(tag, 500) for tag in "ABC"}
    summaries = [{"e": tag, "dl": T0 + dl, "q": 3, "c": [[records[tag][0], 500, n]]}
                 for n, (tag, dl) in enumerate({"A": 80, "B": 90, "C": 200}.items())]
    bus = hub_serving(summaries, dict(records.values()), clock, link_clock, fetch_s=50)
    agent = edge(bus, clock, link_clock, 10.0, summaries)

    run(agent.pull())
    assert arrived(agent) == ["A", "C", "B"]


def test_a_record_past_its_deadline_is_fetched_once_nothing_in_time_waits():
    """The bundled element sets pass their stale time; each one was held
    SUMMARY_ONLY for ever, even on a fast link, so an edge started from
    them got fewer imagers every day."""
    clock, link_clock = FixedClock(NOW), ManualClock()
    sha, raw = _record("omm:40115", 600)
    stale = [{"e": "omm:40115", "dl": T0 - 3600, "q": 0, "c": [[sha, 600, 1]]}]
    agent = edge(hub_serving(stale, {sha: raw}, clock, link_clock), clock, link_clock, 1_000_000.0, stale)

    run(agent.pull())
    assert arrived(agent) == ["omm:40115"]
    assert agent.summary_only == set()


def test_a_late_record_waits_while_the_pull_budget_goes_to_records_in_time():
    clock, link_clock = FixedClock(NOW), ManualClock()
    (sha_a, raw_a), (sha_x, raw_x) = _record("A", 500), _record("X", 500)
    summaries = [
        {"e": "A", "dl": T0 + 3600, "q": 3, "c": [[sha_a, 500, 1]]},
        {"e": "X", "dl": T0 - 3600, "q": 0, "c": [[sha_x, 500, 2]]},
    ]
    bus = hub_serving(summaries, {sha_a: raw_a, sha_x: raw_x}, clock, link_clock, wall_s=0.05)
    agent = edge(bus, clock, link_clock, 1_000_000.0, summaries)

    run(agent.pull(budget_s=0.01))
    assert arrived(agent) == ["A"]
    assert [item.status for item in agent.queue] == ["SUMMARY_ONLY"] and agent.summary_only == {"X"}
    run(agent.pull())
    assert arrived(agent) == ["A", "X"] and agent.summary_only == set()
