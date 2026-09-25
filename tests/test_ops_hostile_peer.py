"""Operator data against a peer that is hostile, forged or buggy.

Anyone who can reach `ops.<hub>.exchange` can push a payload (the leaf link
has no TLS: SECURITY.md, gap 2). The decision log is signed; these tests
hold the merge to what a signature and a durable store promise:

  * a forgery is rejected and recorded, whatever dot it claims;
  * what the replica holds in memory is what it holds on disk, even when a
    merge stops part-way, because peers learn this replica's context from
    memory and never resend what it claims to have;
  * a register a peer sends is one this node can show.

Bugs in the closed core (sentinel/crdt) are strict xfails.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt

import pytest

from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock
from sentinel.crdt import Dot, IntegrityError, NodeKey, SignedLog, TrustStore
from sentinel.crdt.log import Entry
from sentinel.crdt.mvmap import MVMap, Register
from sentinel.ops import OpsService

NOW = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.UTC)
KEYS = {n: NodeKey.generate(n) for n in ("hub", "alpha", "bravo")}
TRUST = {n: k.public_hex() for n, k in KEYS.items()}
CORE = "core bug in sentinel/crdt (closed; fix belongs to its owner): "


def run(coro):
    return asyncio.run(coro)


def ops(node: str, db) -> OpsService:
    return OpsService(node, KEYS[node], TrustStore(TRUST), InProcessBus(), FixedClock(NOW), db_path=str(db))


def authored(node: str, count: int) -> list[Entry]:
    """Genuine entries, signed by `node`, as its own log would hold them."""
    log = SignedLog(node, KEYS[node], TrustStore(TRUST))
    return [log.append("NOTE", {"text": f"note {n}"}, {"event_id": "EV1"}, f"op@{node}", NOW.isoformat())
            for n in range(count)]


def resigned(entry: Entry, key: NodeKey, **changes) -> Entry:
    changed = dataclasses.replace(entry, **changes)
    return dataclasses.replace(changed, sig=key.sign(changed.signed_bytes()).hex())


def memory_matches_disk(service: OpsService, db) -> bool:
    return ops(service.node_id, db).digest() == service.digest()


# ------------------------------------------------------------ signatures
def test_a_forgery_that_reuses_a_dot_is_rejected_and_recorded_not_raised():
    """SignedLog.merge compared digests before verifying the signature, so
    an unsigned forgery that reused a held dot raised IntegrityError (the
    replica 'stops') instead of being rejected and recorded."""
    genuine = authored("alpha", 1)[0]
    log = SignedLog("hub", KEYS["hub"], TrustStore(TRUST))
    log.merge([genuine])
    forged = dataclasses.replace(genuine, body={"text": "forged"}, sig="00" * 64)

    added = log.merge([forged])

    assert added == [] and log.entries[genuine.dot] == genuine
    assert log.rejected[-1]["reason"] == "untrusted-or-bad-signature"


@pytest.mark.parametrize("sig", ["not-hex", "00", "00" * 65], ids=["not-hex", "too-short", "too-long"])
def test_a_signature_that_is_not_hex_is_rejected_and_recorded_not_raised(sig):
    """SignedLog.verify called bytes.fromhex(entry.sig), so a signature that
    was not hex raised ValueError out of merge instead of being rejected."""
    entry = dataclasses.replace(authored("alpha", 1)[0], sig=sig)
    log = SignedLog("hub", KEYS["hub"], TrustStore(TRUST))
    assert log.merge([entry]) == []
    assert log.rejected[-1]["reason"] == "untrusted-or-bad-signature"


# ------------------------------------------------------------ rejections
def hub_without_a_trust_file(db) -> OpsService:
    """What load_identity builds with no SENTINEL_TRUST_FILE: a hub that trusts only itself."""
    return OpsService("hub", KEYS["hub"], TrustStore({"hub": TRUST["hub"]}), InProcessBus(), FixedClock(NOW),
                      db_path=str(db))


def exchange(hub: OpsService, edge: OpsService, times: int = 1) -> None:
    """The edge's push, built from what the hub says it holds, as SyncAgent sends it."""
    for _ in range(times):
        run(hub.merge_payload(edge.payload_for(**hub.contexts())))


def notes_from_alpha(tmp_path, count: int) -> OpsService:
    edge = ops("alpha", tmp_path / "alpha.db")
    for n in range(count):
        run(edge.append("EV1", "NOTE", {"text": f"note {n}"}, "op@alpha"))
    return edge


def test_an_entry_offered_on_every_exchange_is_recorded_once(tmp_path):
    """A rejected entry never enters the context, so the edge offers it again
    on every exchange (every 2 s). Each offer appended another record: the
    list, and /api/ops/digest, grew without bound."""
    hub, edge = hub_without_a_trust_file(tmp_path / "hub.db"), notes_from_alpha(tmp_path, 3)
    exchange(hub, edge, times=10)
    assert len(hub.log.rejected) == 3


def test_the_record_of_rejections_is_bounded_and_keeps_the_newest():
    """Distinct forgeries are distinct records, so a peer that forges without
    end needs a bound. The newest are kept: they say what is arriving now."""
    template = authored("alpha", 1)[0]
    flood = [dataclasses.replace(template, dot=Dot("stranger", n)) for n in range(1, 2_001)]
    log = SignedLog("hub", KEYS["hub"], TrustStore(TRUST))
    log.merge(flood)
    assert len(log.rejected) <= 1_000
    assert log.rejected[-1]["dot"] == ["stranger", 2_000]


def test_a_rejected_entry_is_offered_again_so_trust_granted_later_lets_it_in(tmp_path):
    """Why a rejection is not marked as seen: a peer never offers a dot the
    context claims, so the entry would be lost to this replica for good."""
    hub, edge = hub_without_a_trust_file(tmp_path / "hub.db"), notes_from_alpha(tmp_path, 3)
    exchange(hub, edge, times=3)
    hub.log.trust.add("alpha", TRUST["alpha"])
    exchange(hub, edge)
    assert len(hub.log.entries) == 3


def test_a_forgery_at_a_dot_does_not_keep_the_genuine_entry_out(tmp_path):
    """The other reason: anyone can forge an entry for any dot. Were a
    rejected dot marked as seen, a forgery would suppress the genuine entry."""
    hub, edge = ops("hub", tmp_path / "hub.db"), notes_from_alpha(tmp_path, 1)
    [genuine] = edge.log.entries.values()
    forged = dataclasses.replace(genuine, body={"text": "forged"}, sig="00" * 64)
    run(hub.merge_payload({"log": [forged.to_wire()]}))
    exchange(hub, edge)
    assert hub.log.entries[genuine.dot] == genuine


# ----------------------------------------------------- memory and disk
def test_a_malformed_payload_merges_nothing_rather_than_half(tmp_path):
    """The entries are decoded lazily inside the merge: a genuine entry
    followed by garbage was merged into memory, then the garbage raised
    before anything was saved."""
    db = tmp_path / "hub.db"
    hub = ops("hub", db)
    genuine = authored("alpha", 1)[0]
    with pytest.raises((KeyError, TypeError, ValueError)):
        run(hub.merge_payload({"log": [genuine.to_wire(), {"dot": "garbage"}]}))
    assert memory_matches_disk(hub, db)


def test_what_a_merge_accepted_before_an_integrity_error_is_saved(tmp_path):
    """A trusted node's bug (the same dot, different content, both signed)
    raises by design; what the merge already accepted must be durable, or
    the replica advertises entries it will lose on restart."""
    db = tmp_path / "hub.db"
    hub = ops("hub", db)
    first, second = authored("alpha", 2)
    run(hub.merge_payload({"log": [first.to_wire()]}))
    fresh = authored("bravo", 1)[0]
    conflicting = resigned(first, KEYS["alpha"], body={"text": "rewritten"})

    with pytest.raises(IntegrityError):
        run(hub.merge_payload({"log": [fresh.to_wire(), conflicting.to_wire()]}))
    assert memory_matches_disk(hub, db)


# ------------------------------------------------------------ registers
def register(value) -> dict:
    """Two concurrent writes of `value`: a conflict, so every view reads the key."""
    from sentinel.crdt import DotContext

    return Register({Dot("bravo", 1): value, Dot("alpha", 1): value}, DotContext({"bravo": 1, "alpha": 1})).to_wire()


def _ctx(node, seq):
    from sentinel.crdt import DotContext

    return DotContext({node: seq})


@pytest.mark.parametrize("key,value", [
    ("EV1|triage_status", "not a mapping"),
    ("EV1|triage_status", {"v": "PWNED", "by": "x", "node": "bravo", "at": NOW.isoformat()}),
    ("no-separator", {"v": "x", "by": "x", "node": "bravo", "at": NOW.isoformat()}),
], ids=["value-not-a-mapping", "unknown-triage-status", "key-without-field"])
def test_a_register_a_peer_sends_is_one_this_node_can_show(tmp_path, key, value):
    hub = ops("hub", tmp_path / "hub.db")
    run(hub.annotate("EV1", "triage_status", "WATCH", "capt.lee@hub"))
    run(hub.merge_payload({"reg": {key: register(value)}}))
    hub.annotations("EV1")
    hub.conflicts()
    statuses = [v["v"] for v in hub.annotations("EV1")["triage_status"]["values"]]
    assert set(statuses) <= {"NEW", "WATCH", "MANEUVER_PLANNING", "NO_ACTION", "CLOSED"}


@pytest.mark.xfail(strict=True, reason=(
    "design gap (ADR-005 signs the decision log, not annotations): a register carries no "
    "signature, so any peer that reaches ops.<hub>.exchange can erase an annotation by "
    "claiming, in its context, to have seen the write"))
def test_an_untrusted_peer_cannot_erase_an_annotation(tmp_path):
    hub = ops("hub", tmp_path / "hub.db")
    run(hub.annotate("EV1", "triage_status", "MANEUVER_PLANNING", "capt.lee@hub"))
    erase = Register({}, _ctx("hub", 1_000)).to_wire()       # "I saw it; it is gone"
    run(hub.merge_payload({"reg": {"EV1|triage_status": erase}}))
    assert hub.annotations("EV1")["triage_status"]["values"], "an unsigned register erased the value"


CLAIMED_CONTEXT = (
    "design gap (ADR-005, SECURITY.md gap 4): a register's context is an unsigned claim, and "
    "MVMap.merge_register joins it into the map-wide context this replica advertises as what it "
    "has seen. Bounding that context changes what anti-entropy compares and how a node that lost "
    "its database recovers its own dot counter: an ADR-005 amendment, not a bug fix")


def claimed(context: dict) -> dict:
    """A register that holds one well-formed annotation and claims `context`."""
    from sentinel.crdt import DotContext

    value = {"v": "x", "by": "m", "node": "mallory", "at": NOW.isoformat()}
    return Register({Dot("mallory", 1): value}, DotContext({**context, "mallory": 1})).to_wire()


@pytest.mark.xfail(strict=True, reason=CLAIMED_CONTEXT)
def test_a_claimed_context_does_not_enter_the_context_a_replica_advertises(tmp_path):
    hub = ops("hub", tmp_path / "hub.db")
    run(hub.merge_payload({"reg": {"EV9|note": claimed({"bravo": 1_000_000})}}))
    assert hub.digest()["mv_vv"].get("bravo", 0) < 1_000_000


@pytest.mark.xfail(strict=True, reason=CLAIMED_CONTEXT)
def test_a_claimed_context_does_not_stop_another_nodes_annotations_replicating(tmp_path):
    """The hub's advertised context covers bravo's writes, so bravo never
    offers them: its annotation silently never reaches the hub. Bravo's own
    dot counter then jumps past the claim when it pulls the hub's register."""
    hub = ops("hub", tmp_path / "hub.db")
    run(hub.merge_payload({"reg": {"EV9|note": claimed({"bravo": 1_000_000})}}))
    bravo = ops("bravo", tmp_path / "bravo.db")
    run(bravo.annotate("EV1", "assignee", "lt.kim", "op@bravo"))
    exchange(hub, bravo)
    assert hub.annotations("EV1")["assignee"]["values"], "bravo's annotation never reached the hub"


def test_mvmap_keeps_what_the_peer_never_saw():
    """Control for the xfail above: the same register with an honest context erases nothing."""
    mine = MVMap("hub")
    mine.write("EV1|triage_status", {"v": "WATCH"})
    mine.merge_register("EV1|triage_status", Register({}, _ctx("bravo", 3)))
    assert mine.read("EV1|triage_status")


def test_the_cost_of_an_exchange_does_not_grow_with_the_history_a_peer_claims(tmp_path, monkeypatch):
    """MVMap.missing_for enumerated every dot a register's context covers,
    so one register pushed with a context of {node: 10**9} made the hub
    build a billion-element set on every exchange and stop answering every
    edge. Counted in Dots constructed, for a claim of a million: enough to
    show the enumeration, not enough to exhaust the test runner's memory."""
    from sentinel.crdt import DotContext
    from sentinel.crdt import dots as dots_module

    hub = ops("hub", tmp_path / "hub.db")
    claim = Register({}, DotContext({"bravo": 10**6})).to_wire()
    run(hub.merge_payload({"reg": {"EV1|assignee": claim}}))

    made = {"n": 0}
    real_init = dots_module.Dot.__init__

    def counting_init(self, *args, **kwargs):
        made["n"] += 1
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(dots_module.Dot, "__init__", counting_init)
    hub.payload_for(DotContext().to_wire(), DotContext().to_wire())
    assert made["n"] < 1_000, f"{made['n']} dots enumerated for one exchange"
