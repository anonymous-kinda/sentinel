"""The decision log records what operators did, and nothing it has no writer for.

ADR-005: a CONFLICT is resolved by a person writing a value that supersedes
every concurrent one. That write also appends a signed RESOLUTION entry
naming the field and the values it superseded, so the log shows who
settled a disagreement, and what they overruled, after the register
itself holds only the winner.
"""

import asyncio
import datetime as dt

import pytest

from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock
from sentinel.crdt import NodeKey, TrustStore
from sentinel.crdt.log import KINDS as LOG_KINDS
from sentinel.ops.service import ENTRY_KINDS, OpsService

KEYS = {node: NodeKey.generate(node) for node in ("hub", "alpha")}
TRUST = {node: key.public_hex() for node, key in KEYS.items()}
CLOCK = FixedClock(dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC))
EVENT = "EV-1"


def replica(node: str) -> OpsService:
    return OpsService(node, KEYS[node], TrustStore(TRUST), InProcessBus(), CLOCK)


def run(coro):
    return asyncio.run(coro)


def sync(a: OpsService, b: OpsService) -> None:
    """One anti-entropy exchange each way."""
    run(b.merge_payload(a.payload_for(**b.contexts())))
    run(a.merge_payload(b.payload_for(**a.contexts())))


@pytest.fixture
def conflicted():
    """Both nodes set triage_status while partitioned, then exchange."""
    hub, alpha = replica("hub"), replica("alpha")
    run(alpha.annotate(EVENT, "triage_status", "MANEUVER_PLANNING", "maj.ortiz@alpha"))
    run(hub.annotate(EVENT, "triage_status", "WATCH", "capt.lee@hub"))
    sync(hub, alpha)
    assert hub.annotations(EVENT)["triage_status"]["conflict"]
    return hub, alpha


def resolutions(ops: OpsService) -> list[dict]:
    return [e for e in ops.entries(EVENT) if e["kind"] == "RESOLUTION"]


def test_resolving_a_conflict_appends_a_signed_resolution_naming_what_it_superseded(conflicted):
    hub, _ = conflicted
    status = run(hub.annotate(EVENT, "triage_status", "MANEUVER_PLANNING", "col.reyes@hub"))
    assert not status["triage_status"]["conflict"]
    [entry] = resolutions(hub)
    assert entry["author"] == "col.reyes@hub"
    assert entry["signature_valid"]
    assert entry["body"]["field"] == "triage_status"
    assert entry["body"]["value"] == "MANEUVER_PLANNING"
    superseded = {(v["v"], v["by"], v["node"]) for v in entry["body"]["superseded"]}
    assert superseded == {("MANEUVER_PLANNING", "maj.ortiz@alpha", "alpha"), ("WATCH", "capt.lee@hub", "hub")}


def test_the_resolution_reaches_the_other_node_verified(conflicted):
    hub, alpha = conflicted
    run(hub.annotate(EVENT, "triage_status", "WATCH", "col.reyes@hub"))
    sync(hub, alpha)
    assert not alpha.annotations(EVENT)["triage_status"]["conflict"]
    [entry] = resolutions(alpha)
    assert entry["node"] == "hub" and entry["signature_valid"]
    assert hub.digest()["log"] == alpha.digest()["log"]


def test_a_write_with_no_conflict_appends_nothing():
    hub = replica("hub")
    run(hub.annotate(EVENT, "triage_status", "WATCH", "capt.lee@hub"))
    run(hub.annotate(EVENT, "triage_status", "CLOSED", "capt.lee@hub"))
    assert hub.entries(EVENT) == []


def test_the_log_accepts_only_the_kinds_something_writes():
    assert ENTRY_KINDS == ("DECISION", "NOTE", "RESOLUTION")
    assert set(ENTRY_KINDS) <= set(LOG_KINDS)
    with pytest.raises(ValueError, match="AI_DRAFT_CONFIRMED"):
        run(replica("hub").append(EVENT, "AI_DRAFT_CONFIRMED", {}, "op@hub"))
