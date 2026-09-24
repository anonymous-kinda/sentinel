"""Property tests for the operator-data CRDTs (ADR-005).

A stateful model drives three replicas through random writes and log
appends, and a network that drops, duplicates, reorders and delivers
anti-entropy payloads built from stale knowledge of the receiver - the
DDIL link. Invariants:

  convergence   after everyone syncs, every replica holds identical state
  no loss       the log holds exactly the entries that were appended
  no silent     every register write is either visible or was causally
  overwrite     overwritten by a write whose author had seen it
  conflicts     concurrent writes to one key are all visible
"""

import copy

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, precondition, rule

from sentinel.crdt import Dot, DotContext, IntegrityError, MVMap, NodeKey, SignedLog, TrustStore
from sentinel.crdt.log import Entry

NODES = ["hub", "alpha", "bravo"]
KEYS = ["EV1:triage_status", "EV1:assignee", "EV2:triage_status", "policy:red_pc"]
KEYPAIRS = {n: NodeKey.generate(n) for n in NODES}


def trust() -> TrustStore:
    return TrustStore({n: k.public_hex() for n, k in KEYPAIRS.items()})


class Replica:
    def __init__(self, node: str):
        self.node = node
        self.log = SignedLog(node, KEYPAIRS[node], trust())
        self.mv = MVMap(node)

    def payload_for(self, log_ctx: DotContext, mv_ctx: DotContext):
        return (
            [e.to_wire() for e in self.log.missing_for(log_ctx)],
            {k: copy.deepcopy(r) for k, r in self.mv.missing_for(mv_ctx).items()},
        )

    def receive(self, payload) -> None:
        entries, registers = payload
        self.log.merge(Entry.from_wire(e) for e in entries)
        for key, reg in registers.items():
            self.mv.merge_register(key, copy.deepcopy(reg))


def sync_all(replicas: dict[str, Replica]) -> None:
    for _ in range(3):
        for a in replicas.values():
            for b in replicas.values():
                if a is not b:
                    b.receive(a.payload_for(b.log.ctx, b.mv.ctx))


class DDILNetwork(RuleBasedStateMachine):
    payloads = Bundle("payloads")

    def __init__(self):
        super().__init__()
        self.replicas = {n: Replica(n) for n in NODES}
        self.appends = 0
        self.writes: list[tuple[Dot, str, frozenset]] = []   # (dot, key, dots it overwrote)
        self.stale: dict[tuple[str, str], tuple[DotContext, DotContext]] = {}

    @rule(node=st.sampled_from(NODES), key=st.sampled_from(KEYS), value=st.integers(0, 5))
    def write(self, node, key, value):
        r = self.replicas[node]
        seen = frozenset(d for d, _ in r.mv.read(key))
        dot = r.mv.write(key, {"v": value, "by": node})
        self.writes.append((dot, key, seen))

    @rule(node=st.sampled_from(NODES), text=st.text(max_size=8))
    def append(self, node, text):
        self.replicas[node].log.append("NOTE", {"text": text}, {"event_id": "EV1"}, f"op@{node}", "t")
        self.appends += 1

    @rule(target=payloads, src=st.sampled_from(NODES), dst=st.sampled_from(NODES), stale=st.booleans())
    def send(self, src, dst, stale):
        """Build a payload from what src believes dst knows - possibly stale."""
        d = self.replicas[dst]
        if stale and (src, dst) in self.stale:
            log_ctx, mv_ctx = self.stale[(src, dst)]
        else:
            log_ctx, mv_ctx = d.log.ctx.copy(), d.mv.ctx.copy()
            self.stale[(src, dst)] = (log_ctx, mv_ctx)
        return (dst, self.replicas[src].payload_for(log_ctx, mv_ctx))

    @rule(p=payloads)
    def deliver(self, p):
        """Deliver in any order, any number of times (duplicates), or never (drops)."""
        dst, payload = p
        self.replicas[dst].receive(copy.deepcopy(payload))

    @precondition(lambda self: self.writes or self.appends)
    @rule()
    def converge(self):
        sync_all(self.replicas)
        logs = {r.log.state_digest() for r in self.replicas.values()}
        mvs = {r.mv.state_digest() for r in self.replicas.values()}
        assert len(logs) == 1, "logs diverged after full sync"
        assert len(mvs) == 1, "registers diverged after full sync"

        any_replica = next(iter(self.replicas.values()))
        assert len(any_replica.log.entries) == self.appends, "log lost or duplicated entries"

        for key in KEYS:
            written = {dot for dot, k, _ in self.writes if k == key}
            overwritten = set().union(*[seen for _, k, seen in self.writes if k == key]) if written else set()
            expected = written - overwritten
            visible = {d for d, _ in any_replica.mv.read(key)}
            assert visible == expected, f"{key}: visible {visible} != expected {expected}"

    @invariant()
    def never_more_log_entries_than_appended(self):
        for r in self.replicas.values():
            assert len(r.log.entries) <= self.appends


TestDDILNetwork = DDILNetwork.TestCase
TestDDILNetwork.settings = settings(
    max_examples=150, stateful_step_count=40, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


# --- algebraic properties on reachable states --------------------------------
@pytest.mark.parametrize("pair", [("hub", "alpha"), ("alpha", "bravo")])
def test_register_merge_is_commutative_and_idempotent(pair):
    a, b = Replica(pair[0]), Replica(pair[1])
    a.mv.write("K", 1)
    b.mv.write("K", 2)
    a.mv.write("K", 3)
    ab = copy.deepcopy(a)
    ab.receive(b.payload_for(DotContext(), DotContext()))
    ba = copy.deepcopy(b)
    ba.receive(a.payload_for(DotContext(), DotContext()))
    assert ab.mv.state_digest() == ba.mv.state_digest()
    once = ab.mv.state_digest()
    ab.receive(b.payload_for(DotContext(), DotContext()))
    assert ab.mv.state_digest() == once
    assert {v for _, v in ab.mv.read("K")} == {3, 2}, "concurrent writes both survive: a CONFLICT"


def test_resolving_a_conflict_supersedes_both_values():
    a, b = Replica("hub"), Replica("alpha")
    a.mv.write("K", "MANEUVER")
    b.mv.write("K", "MONITOR")
    sync_all({"hub": a, "alpha": b})
    assert a.mv.conflicted("K")
    a.mv.write("K", "MANEUVER")           # written after seeing both values
    sync_all({"hub": a, "alpha": b})
    assert [v for _, v in b.mv.read("K")] == ["MANEUVER"]


def test_tampered_entry_is_rejected_not_merged():
    a, b = Replica("hub"), Replica("alpha")
    entry = a.log.append("DECISION", {"decision": "MONITOR"}, {"event_id": "EV1"}, "op", "t")
    forged = Entry.from_wire({**entry.to_wire(), "body": {"decision": "MANEUVER"}})
    assert b.log.merge([forged]) == []
    assert b.log.rejected and b.log.rejected[0]["reason"] == "untrusted-or-bad-signature"


def test_untrusted_node_is_rejected():
    stranger = NodeKey.generate("stranger")
    log = SignedLog("stranger", stranger, TrustStore({"stranger": stranger.public_hex()}))
    entry = log.append("NOTE", {}, {}, "x", "t")
    receiver = Replica("hub")
    assert receiver.log.merge([entry]) == []


def test_same_dot_with_different_content_raises():
    a = Replica("hub")
    e1 = a.log.append("NOTE", {"n": 1}, {}, "op", "t")
    other = SignedLog("hub", KEYPAIRS["hub"], trust())
    e2 = other.append("NOTE", {"n": 2}, {}, "op", "t")      # same dot (hub,1), different body
    assert e1.dot == e2.dot
    with pytest.raises(IntegrityError):
        a.log.merge([e2])
