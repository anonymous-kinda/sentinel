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
@pytest.mark.xfail(strict=True, reason=CORE + (
    "SignedLog.merge compares an incoming entry's digest with the one already held for its "
    "dot before verifying its signature, so an unsigned forgery that reuses a dot raises "
    "IntegrityError (the replica 'stops') instead of being rejected and recorded"))
def test_a_forgery_that_reuses_a_dot_is_rejected_and_recorded_not_raised():
    genuine = authored("alpha", 1)[0]
    log = SignedLog("hub", KEYS["hub"], TrustStore(TRUST))
    log.merge([genuine])
    forged = dataclasses.replace(genuine, body={"text": "forged"}, sig="00" * 64)

    added = log.merge([forged])

    assert added == [] and log.entries[genuine.dot] == genuine
    assert log.rejected[-1]["reason"] == "untrusted-or-bad-signature"


@pytest.mark.xfail(strict=True, reason=CORE + (
    "SignedLog.verify calls bytes.fromhex(entry.sig), so a signature that is not hex raises "
    "ValueError out of merge instead of being rejected and recorded"))
def test_a_signature_that_is_not_hex_is_rejected_and_recorded_not_raised():
    entry = dataclasses.replace(authored("alpha", 1)[0], sig="not-hex")
    log = SignedLog("hub", KEYS["hub"], TrustStore(TRUST))
    assert log.merge([entry]) == []
    assert log.rejected[-1]["reason"] == "untrusted-or-bad-signature"


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


def test_mvmap_keeps_what_the_peer_never_saw():
    """Control for the xfail above: the same register with an honest context erases nothing."""
    mine = MVMap("hub")
    mine.write("EV1|triage_status", {"v": "WATCH"})
    mine.merge_register("EV1|triage_status", Register({}, _ctx("bravo", 3)))
    assert mine.read("EV1|triage_status")


@pytest.mark.xfail(strict=True, reason=CORE + (
    "MVMap.missing_for enumerates every dot a register's context covers (DotContext.dots()), "
    "so one register pushed with a context of {node: 10**9} makes every later anti-entropy "
    "exchange build a billion-element set: the hub stops answering every edge"))
def test_a_register_context_claiming_a_huge_history_cannot_stall_anti_entropy(tmp_path):
    import signal

    from sentinel.crdt import DotContext

    hub = ops("hub", tmp_path / "hub.db")
    claim = Register({}, DotContext({"bravo": 10**9})).to_wire()
    run(hub.merge_payload({"reg": {"EV1|assignee": claim}}))

    def expire(_signum, _frame):
        raise TimeoutError("payload_for did not answer within 5 s")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(5)
    try:
        hub.payload_for(DotContext().to_wire(), DotContext().to_wire())
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
