"""The edge against a hub that is hostile, buggy, or corrupted in transit.

The edge already knows, from the manifest, which record it asked for: its
item id and the first 16 hex digits of its sha256. A fetch reply's headers
are the hub's claims about the bytes; the bytes themselves can be hashed.
These tests hold the agent to what it can check, and hold the protocol to
the DDIL link it runs on.

Bugs in the closed core (sentinel/sync) are strict xfails: the suite stays
green, the bug stays recorded, and the xfail turns red the day it is fixed.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import datetime as dt
import hashlib
import pathlib
from collections.abc import Callable

import pytest

from sentinel.api.records import CompositeRecords
from sentinel.bus import InProcessBus, Msg, RequestTimeout, subjects
from sentinel.clock import FixedClock
from sentinel.conjunction.exercise import generate
from sentinel.conjunction.sync_adapter import ConjunctionRecords
from sentinel.crdt import TrustStore, codec
from sentinel.linkstate import LinkMonitor
from sentinel.ops import OpsService
from sentinel.passes.element_store import ElementStore
from sentinel.passes.sync_adapter import PREFIX as ELEMENT_PREFIX
from sentinel.passes.sync_adapter import ElementRecords
from sentinel.sync import SyncAgent, SyncServer
from sentinel.sync.agent import LINK_ERRORS

from .conftest import EPOCH, KEYS, TRUST, Node

SNAPSHOT = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "omm" / "celestrak-resource-20260924.json"
CORE = "core bug in sentinel/sync (closed; fix belongs to its owner): "

Tamper = Callable[[bytes, dict[str, str]], tuple[bytes, dict[str, str]]]


@dataclasses.dataclass
class Link:
    bus: InProcessBus
    clock: FixedClock
    hub: Node
    edge: Node
    server: SyncServer
    agent: SyncAgent


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def link() -> Link:
    bus = InProcessBus()
    clock = FixedClock(EPOCH + dt.timedelta(minutes=1))
    hub, edge = Node("hub", bus, clock), Node("alpha", bus, clock)
    server = SyncServer(bus, hub.records, hub.ops, "hub")

    async def setup():
        await server.start()
        for item in generate(EPOCH):
            if item.release_at <= clock.now():
                await hub.conj.ingest(item.kvn.encode(), "exercise", "EXERCISE")

    run(setup())
    agent = SyncAgent(bus, edge.records, edge.ops, clock, "alpha", "hub", LinkMonitor())
    return Link(bus, clock, hub, edge, server, agent)


def tamper_fetch(link: Link, tamper: Tamper, one_record: bool = False) -> None:
    """Put a man in the middle of the hub's fetch replies: every reply, or
    every reply for the first record the edge asks for."""
    target: list[str] = []

    async def responder(msg: Msg) -> tuple[bytes, dict[str, str]]:
        body, headers = await link.server._fetch(msg)
        sha = codec.decode(msg.data)["sha"]
        target[:] = target or [sha]
        if one_record and sha != target[0]:
            return body, headers
        return tamper(body, dict(headers))

    run(link.bus.serve(subjects.sync_fetch("hub"), responder))


def announced(node: Node) -> set[str]:
    return {sha for compact in node.conj.manifest() for sha, _, _ in compact["c"]}


# ------------------------------------------------------------ the bytes
def corrupted(body, headers):
    """One line added in transit. The CDM still parses; its hash does not match."""
    return body + b"COMMENT altered in transit\n", headers


def header_stripped(body, headers):
    headers.pop("Sentinel-Sha256")
    return corrupted(body, headers)


def substituted_by(link: Link) -> Tamper:
    """The hub answers with a genuine record, just not the one asked for."""
    other = sorted(announced(link.hub))[0]

    def tamper(body, headers):
        return link.hub.records.get(other)

    return tamper


@pytest.mark.parametrize("mode", ["corrupted", "header-stripped", "substituted"])
def test_the_edge_admits_only_the_bytes_it_asked_for(link, mode):
    tamper = {"corrupted": corrupted, "header-stripped": header_stripped}.get(mode) or substituted_by(link)
    tamper_fetch(link, tamper)
    run(link.agent.cycle())

    held = {row.sha256[:16] for row in link.edge.conj.store.all_cdms()}
    assert held <= announced(link.hub), "the edge admitted a record the hub never announced"
    for arrival in link.agent.arrivals:
        assert link.edge.records.has(arrival["sha"]), f"{arrival['sha']} marked arrived but never received"
        assert arrival["hash_ok"], "a record whose hash did not match was admitted"


def test_intact_bytes_without_their_sha256_header_are_not_a_match(link):
    """hash_ok is a comparison with the hub's claim; with no claim there is
    nothing to compare, so the record is refused and asked for again."""

    def strip_hash(body, headers):
        headers.pop("Sentinel-Sha256")
        return body, headers

    tamper_fetch(link, strip_hash)
    run(link.agent.cycle())
    assert link.agent.arrivals == []
    assert list(link.edge.conj.store.all_cdms()) == []
    assert {item.status for item in link.agent.queue} == {"QUEUED"}


def test_a_missing_data_class_header_cannot_relabel_exercise_data_as_real(link):
    """Refutes the lead that a missing Sentinel-Data-Class turns data REAL:
    every non-REAL producer marks its CDMs at the source (ORIGINATOR), and
    the mark decides the class whatever the header says."""

    def strip_class(body, headers):
        headers.pop("Sentinel-Data-Class")
        return body, headers

    tamper_fetch(link, strip_class)
    run(link.agent.cycle())
    classes = {row.data_class for row in link.edge.conj.store.all_cdms()}
    assert classes == {"EXERCISE"}


def bad_class(body, headers):
    """The bytes are right; the module's own admission cannot read the reply."""
    headers["Sentinel-Data-Class"] = "BANANA"
    return body, headers


def test_one_unreadable_reply_does_not_block_every_record_behind_it(link):
    tamper_fetch(link, bad_class, one_record=True)
    for _ in range(2):
        with contextlib.suppress(ValueError):  # run() logs it; the next cycle is what matters
            run(link.agent.cycle())
    held = {row.sha256[:16] for row in link.edge.conj.store.all_cdms()}
    assert len(announced(link.hub) - held) == 1, "only the unreadable record is missing"


@pytest.mark.parametrize("tamper", [bad_class, corrupted], ids=["unreadable", "corrupted"])
def test_a_refused_record_is_retried_with_back_off_not_every_cycle(link, tamper):
    """Every attempt costs a round trip on a thin link, so a record the edge
    refuses sits out a growing number of pulls; it arrives once the hub's
    reply is good again."""
    attempts = []

    def counted(body, headers):
        attempts.append(1)
        return tamper(body, headers)

    tamper_fetch(link, counted, one_record=True)
    cycles = 8
    for _ in range(cycles):
        run(link.agent.cycle())
    assert 2 <= len(attempts) <= cycles // 2, f"asked {len(attempts)} times in {cycles} cycles"

    run(link.bus.serve(subjects.sync_fetch("hub"), link.server._fetch))   # the hub answers honestly again
    for _ in range(4 * cycles):
        run(link.agent.cycle())
    held = {row.sha256[:16] for row in link.edge.conj.store.all_cdms()}
    assert announced(link.hub) <= held


# ------------------------------------------------------- the manifest
def hostile_manifest(link: Link, extra: list[dict]) -> None:
    async def responder(msg: Msg) -> tuple[bytes, dict[str, str]]:
        manifest = extra + link.hub.records.manifest()
        return codec.encode(manifest), {"Sentinel-Digest": codec.digest(manifest)}

    run(link.bus.serve(subjects.sync_manifest("hub"), responder))


BOGUS = {"e": "bogus", "dl": "soon", "q": 9, "c": [["0" * 16, 10, 0]]}


@pytest.mark.xfail(strict=True, reason=CORE + (
    "fetch_manifest() stores the digest before apply_manifest() runs, and _rebuild_queue() "
    "rejects the whole manifest on one malformed entry; the next cycle is told 'unchanged' "
    "and the queue is never built, so no record ever arrives"))
def test_one_malformed_manifest_entry_does_not_stop_the_edge_fetching_the_rest(link):
    hostile_manifest(link, [BOGUS])
    for _ in range(2):
        with contextlib.suppress(TypeError, ValueError, KeyError):  # run() logs these
            run(link.agent.cycle())
    held = {row.sha256[:16] for row in link.edge.conj.store.all_cdms()}
    assert announced(link.hub) <= held


def test_a_malformed_hub_summary_never_breaks_the_edge_event_list(link):
    """Whatever the core does with the manifest, a summary the edge stores
    must be one it can show: one bad entry must not 500 /api/events."""
    genuine = link.hub.records.manifest()
    bogus = [
        {"e": "no-tca", "dl": 1_790_000_000, "q": 1, "c": []},
        {**genuine[0], "e": "bad-band", "b": "Z"},
        {**genuine[0], "e": "bad-time", "t": "tomorrow"},
        {**genuine[0], "e": "bad-names", "p": None},
        {**genuine[0], "e": "bad-class", "dc": "Q"},
        {**genuine[0], "e": "pc-above-one", "pc": 0.5},
        {**genuine[0], "e": "pc-overflows", "pc": 400.0},
        {**genuine[0], "e": "nan-miss", "md": float("nan")},
        {**genuine[0], "e": "int-sha", "c": [[7, 100, 0]]},
        {**genuine[0], "e": "year-10000", "t": 253_402_300_800},
        {**genuine[0], "e": 12},
        ["not", "a", "summary"],
    ]
    link.edge.records.put_summaries(bogus + genuine, "hub")
    listed = {e["event_id"] for e in link.edge.conj.list_events("all")}
    assert listed == {compact["e"] for compact in genuine}
    for compact in bogus:
        if isinstance(compact, dict) and isinstance(compact["e"], str):
            assert link.edge.conj.event_detail(compact["e"]) is None


# --------------------------------------------------------- item identity
@pytest.fixture
def element_link() -> tuple[Link, set[int], ElementStore]:
    bus = InProcessBus()
    clock = FixedClock(dt.datetime(2026, 9, 24, 7, 0, tzinfo=dt.UTC))
    hub, edge = Node("hub", bus, clock), Node("alpha", bus, clock)
    hub_elements, edge_elements = ElementStore(), ElementStore()
    hub_elements.load_snapshot(SNAPSHOT, "celestrak")
    offered = set(sorted(hub_elements.latest())[:3])
    hub.records = CompositeRecords(
        ConjunctionRecords(hub.conj), {ELEMENT_PREFIX: ElementRecords(hub_elements, clock, offered=offered.__contains__)}
    )
    edge.records = CompositeRecords(ConjunctionRecords(edge.conj), {ELEMENT_PREFIX: ElementRecords(edge_elements, clock)})
    server = SyncServer(bus, hub.records, hub.ops, "hub")
    run(server.start())
    agent = SyncAgent(bus, edge.records, edge.ops, clock, "alpha", "hub", LinkMonitor())
    return Link(bus, clock, hub, edge, server, agent), offered, edge_elements


@pytest.mark.xfail(strict=True, reason=CORE + (
    "_fetch() routes a record by the reply's Sentinel-Event-Id header alone; without it the "
    "item id the manifest gave (WantItem.event_id) is ignored, an element set is handed to "
    "the CDM parser, quarantined as PARSE_ERROR, and the item is marked ARRIVED"))
def test_a_record_is_filed_under_the_item_the_manifest_named(element_link):
    link, offered, edge_elements = element_link

    def strip_item_id(body, headers):
        headers.pop("Sentinel-Event-Id")
        return body, headers

    tamper_fetch(link, strip_item_id)
    run(link.agent.cycle())
    assert link.edge.conj.quarantined() == []
    assert set(edge_elements.latest()) == offered


# ------------------------------------------------------ admission control
class SmallRecords:
    """Opaque records under 2 kB, so the link monitor's measured rate stays
    where the test puts it (it only learns from transfers of 2 kB or more)."""

    def __init__(self, summaries: list[dict] | None = None, records: dict[str, bytes] | None = None):
        self.summaries = summaries or []
        self.records = records or {}
        self.held: set[str] = set()

    def manifest(self) -> list[dict]:
        return self.summaries

    def get(self, sha16):
        raw = self.records.get(sha16)
        if raw is None:
            return None
        return raw, {"Sentinel-Sha256": hashlib.sha256(raw).hexdigest(), "Sentinel-Event-Id": "x",
                     "Sentinel-Data-Class": "REAL"}

    def has(self, sha16):
        return sha16 in self.held

    def put_summaries(self, summaries, origin):
        return None

    async def ingest(self, raw, source, data_class, item_id):
        sha = hashlib.sha256(raw).hexdigest()
        self.held.add(sha[:16])
        return {"status": "accepted", "sha256": sha, "verification": None}


def _record(tag: str, size: int) -> tuple[str, bytes]:
    raw = tag.encode().ljust(size, b".")
    return hashlib.sha256(raw).hexdigest()[:16], raw


@pytest.mark.xfail(strict=True, reason=CORE + (
    "pull() reads the clock once before the loop (and bytes_ahead is reset but never "
    "added to), so a record is admitted against a deadline measured before the records "
    "ahead of it spent the link"))
def test_admission_control_counts_the_time_spent_on_records_ahead():
    now = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.UTC)
    clock = FixedClock(now)
    sha_a, raw_a = _record("A", 500)
    sha_b, raw_b = _record("B", 500)
    summaries = [
        {"e": "A", "dl": int(now.timestamp()) + 80, "q": 3, "c": [[sha_a, 500, 1]]},
        {"e": "B", "dl": int(now.timestamp()) + 90, "q": 3, "c": [[sha_b, 500, 2]]},
    ]
    bus = InProcessBus()
    server = SyncServer(bus, SmallRecords(summaries, {sha_a: raw_a, sha_b: raw_b}), None, "hub")
    run(server.start())

    async def fetch_takes_50_s(msg: Msg):
        clock.advance(50)            # 500 B at 10 B/s: what the link monitor predicts
        return await server._fetch(msg)

    run(bus.serve(subjects.sync_fetch("hub"), fetch_takes_50_s))
    monitor = LinkMonitor(rate_bytes_per_s=10.0)
    agent = SyncAgent(bus, SmallRecords(), None, clock, "alpha", "hub", monitor)
    agent.apply_manifest(summaries)
    run(agent.pull())

    status = {item.event_id: item.status for item in agent.queue}
    arrived = {a["event_id"] for a in agent.arrivals}
    assert "A" in arrived, "A fits: 50 s against 80 s"
    assert status.get("B") == "SUMMARY_ONLY", "after A, B has 40 s left and needs 50 s"


# ---------------------------------------------------------------- timeouts
class ThinLinkBus(InProcessBus):
    """A link that moves `rate` bytes per second. A request whose reply
    needs longer than the requester's timeout to cross is lost, exactly as
    a NATS request is."""

    def __init__(self, rate_bytes_per_s: float):
        super().__init__()
        self.rate = rate_bytes_per_s

    async def request(self, subject, data, timeout, headers=None):
        reply = await super().request(subject, data, 3600.0, headers)
        if (len(data) + len(reply.data)) / self.rate > timeout:
            raise RequestTimeout(subject)
        return reply


@pytest.mark.xfail(strict=True, reason=CORE + (
    "fetch_manifest() always allows the time for 4000 bytes (_timeout(4000)); a manifest "
    "that needs longer to cross the measured link times out every cycle, identically, "
    "forever, and the edge never sees a single summary"))
def test_a_manifest_larger_than_4_kb_still_reaches_the_edge_on_a_limited_link():
    rate = 1000.0                                  # ~8 kbit/s: the LIMITED scenario
    now = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.UTC)
    clock = FixedClock(now)
    summaries = [
        {"e": f"EVENT-{n:03d}", "dl": int(now.timestamp()) + 3600 * (n + 1), "q": 1,
         "p": ["99001", "EXSAT-1"], "s": [str(99100 + n), f"EX-DEB {n}"], "t": int(now.timestamp()) + 3600 * (n + 9),
         "pad": "x" * 120, "c": [[f"{n:016x}", 3000, 1]]}
        for n in range(80)
    ]
    assert len(codec.encode(summaries)) > 6 * rate + 1.5 * 4000   # longer than the agent waits
    bus = ThinLinkBus(rate)
    hub_ops = OpsService("hub", KEYS["hub"], TrustStore(TRUST), bus, clock)
    run(SyncServer(bus, SmallRecords(summaries), hub_ops, "hub").start())
    edge_ops = OpsService("alpha", KEYS["alpha"], TrustStore(TRUST), bus, clock)
    agent = SyncAgent(bus, SmallRecords(), edge_ops, clock, "alpha", "hub", LinkMonitor(rate_bytes_per_s=rate))

    for _ in range(8):
        try:
            run(agent.cycle())
        except LINK_ERRORS:
            agent.link.observe_failure()
    assert agent.manifest_digest is not None and agent.queue, "the edge never received the manifest"


def test_the_composite_routes_a_summary_without_an_item_id_to_rejection_not_to_a_crash(link):
    genuine = link.hub.records.manifest()
    composite = CompositeRecords(link.edge.records, {ELEMENT_PREFIX: ElementRecords(ElementStore(), link.clock)})
    composite.put_summaries([{"dl": 1}, ["x"], None, *genuine], "hub")
    assert {e["event_id"] for e in link.edge.conj.list_events("all")} == {c["e"] for c in genuine}



# ---------------------------------------------------- a hostile requester
@pytest.mark.parametrize("prefix", ["%", "_" * 16, "", "0%", "0" * 15 + "_"])
def test_a_record_prefix_is_hex_digits_not_a_pattern(link, element_link, prefix):
    """A fetch names a record by the first hex digits of its sha256. Read as
    a SQL LIKE pattern (or a str prefix), "%" or "" served an arbitrary
    record, including ones the hub does not offer, to anyone on the subject.
    The node's records are the composite the app assembles (api/records.py)."""
    conjunctions = CompositeRecords(link.hub.records, {})
    elements = element_link[0].hub.records
    for records in (conjunctions, elements):
        assert records.get(prefix) is None
        assert not records.has(prefix)
