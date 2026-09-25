# 8. Operator data: signed CRDTs

## What you will learn

- Why a decision, a note or a triage status needs a different replication model from a CDM.
- How dots and causal contexts let two nodes agree on "what have you seen" without trusting a clock.
- How the signed decision log and the multi-value registers merge, and why neither can lose a write.
- How the exchange rides each sync cycle within a byte budget, and what a trust store decides.
- Where the model is weak today: annotation registers carry no signature.

## Why it exists

Operators at the hub and at an edge keep working while the link is down. Both can write about the same event. Take one real case from the DENIED scenario: while the link is cut, the edge operator sets an event's triage status to MANEUVER_PLANNING and the hub operator sets the same event to WATCH. Then the link comes back.

The common answer is last-writer-wins (LWW): keep the value with the later timestamp. It converges, but it silently throws one operator's work away. Nobody is told. The timestamps come from two clocks that may disagree, so "later" may not even be true. For a triage status that is bad. For a maneuver decision it is unacceptable: the log of decisions is the record of what was decided, by whom, against which data.

Sentinel's rule is different. A write survives until someone who had seen it replaces it. Two writes made without seeing each other are both kept and shown as a CONFLICT, with who wrote each one and where. A person resolves it by writing a new value, and that resolution goes into the signed log with the values it overruled.

What this buys, per ADR-005: decisions made offline merge without loss, and concurrent edits show instead of vanishing. The DENIED and INTERMITTENT scenarios measure it on real processes (`docs/ddil-results.md`; chapter 9 explains how).

## Concepts

### Replicas, merge and the three laws

Every node holds a full copy of the operator data: a replica. Replicas exchange state, and each one folds what it receives into what it has with a merge function. If merge is:

- **commutative** (merge A then B equals merge B then A),
- **associative** (grouping does not matter), and
- **idempotent** (merging the same thing twice changes nothing),

then the order, duplication and loss of messages cannot matter. Once every replica has received everything, directly or through others, they hold the same state. A data type with such a merge is a state-based CRDT (conflict-free replicated data type). A DDIL link drops, repeats and reorders, so this is exactly the guarantee it needs.

### Why last-writer-wins loses data

```
edge-alpha (link down)                      hub (link down)
06:00  triage = MANEUVER_PLANNING
                                            06:01  triage = WATCH
------------------------- link returns -------------------------
LWW:            WATCH  (MANEUVER_PLANNING is gone; nobody is told)
multi-value:    { MANEUVER_PLANNING  by maj.ortiz@edge-alpha,
                  WATCH              by capt.lee@hub }  -> CONFLICT
```

The multi-value register never picks. It keeps both until a person does.

### Dots: a name for every write

A **dot** is a pair `(node, seq)`. Each node numbers its own writes 1, 2, 3 and so on. So `(edge-alpha, 3)` is edge-alpha's third write. Dots are unique without any coordination, and they say nothing about time. `Dot` in `sentinel/crdt/dots.py` is this pair.

### Causal context: a version vector and a cloud

A replica's **causal context** is the set of dots it has seen. Listing every dot would grow forever, so it is compressed. A **version vector** `{node: n}` means "I have seen dots 1 to n from that node". A DDIL link delivers out of order, so a replica can hold dot 5 before dot 4. Dots past a gap wait in the **cloud** until the gap fills:

```
seen from edge-alpha:   1  2  3  .  5  .  7
vv    = {edge-alpha: 3}
cloud = {(edge-alpha, 5), (edge-alpha, 7)}

(edge-alpha, 4) arrives  ->  vv = {edge-alpha: 5}, cloud = {(edge-alpha, 7)}
```

`DotContext.compact` does that folding. `DotContext` is used in two places: the log's context says which entries a replica holds, and each register's context says which writes to that key it has seen.

### Asking "have you seen everything I have?"

Anti-entropy needs one question answered cheaply: does my peer's context cover this item's context? The obvious way is to enumerate every dot of the item's context and look each one up. That is a trap. A context arriving from a peer can claim `{bravo: 1000000000}` in a few bytes, and enumerating it builds a billion objects. A review found exactly this in an earlier version, and one register made the hub stop answering every edge.

`DotContext.covers` answers without enumerating. It compares version-vector entries directly and checks only the cloud dots. So the cost is the size of the context as sent, never the history it claims. That is correct because of one invariant that `compact` keeps: the dot right after a node's prefix is never in the cloud (it would have been folded into the prefix). So if the other side's prefix for a node is longer than yours, the dot just after your prefix is one you have not seen. `tests/property/test_crdt.py::test_covers_answers_whether_every_dot_was_seen_without_enumerating_them` holds `covers` to the slow definition on random contexts.

### Two data types

Operator data uses two CRDTs, because it has two shapes.

**A grow-only log** for things that happened: decisions, notes and resolutions. The state is a map from dot to entry. Merge is set union. Entries are immutable, so there is nothing to conflict. Display order is derived, not stored: each entry carries a **Lamport clock**, a counter that is one more than the highest the author had seen, so an entry written after reading another sorts after it. Ties break on node, then seq. The wall time is kept for people and never used for ordering.

**A map of multi-value registers** for things that are set: `triage_status`, `assignee` and `note` on each event. The key is `<event_id>|<field>`. Each register holds a store (`{dot: value}`, the values currently visible) and its own context (every write to that key it has seen). A write replaces the values its author could see. The join of two register states, from the docstring of `sentinel/crdt/mvmap.py`:

```
keep (d, v) from A   if d is in B.store, or d is not in B.ctx
keep (d, v) from B   if d is in A.store, or d is not in A.ctx
ctx = A.ctx ∪ B.ctx
```

Read it as: a value survives unless the other side has seen its dot and no longer stores it. "Seen but no longer stored" means someone overwrote it knowingly. Worked through:

```
hub:   store {(hub,1): WATCH}                 ctx {hub:1}
edge:  store {(edge,1): MANEUVER_PLANNING}    ctx {edge:1}
join:  both kept, since neither side has seen the other's dot   -> CONFLICT

A person at the hub writes MANEUVER_PLANNING, having seen both:
hub:   store {(hub,2): MANEUVER_PLANNING}     ctx {hub:2, edge:1}
join with the edge's old state: (edge,1) is in the hub's ctx but not its
store, so it was overwritten; it is dropped. One value, no conflict.
```

### Signatures, the hash chain and canonical bytes

The log is also the record, so its entries are signed.

- **Ed25519.** Each node has a private key. An entry's signature covers every field except the signature itself: dot, Lamport clock, wall time, kind, event reference, body, author and `prev`.
- **Canonical CBOR** (RFC 8949, section 4.2). The same content always encodes to the same bytes, whatever order a dictionary happens to hold its keys in. So a signature and a digest are properties of the content, not of the encoder.
- **Hash chain per node.** Each entry's `prev` is the digest of the same node's previous entry. A node's history cannot be edited in the middle without breaking a link.
- **What a signature proves.** It binds an entry to a node, not to a person. `author` is whatever operator name the node recorded, which today comes from a proxy header (`SECURITY.md`, gap 1).

### Trust stores

A **trust store** maps node ids to public keys. A replica merges a log entry only if its signature verifies under the key of the node in the entry's dot. Whether an entry is valid is a fixed function of the entry and the trust store, so filtering before the union keeps merge a join. Replicas with the same trust store converge to the same log. A replica with a smaller trust store converges to a smaller log, on purpose.

## Code walkthrough

Read the pure data types first, then the service that persists them, then the exchange.

### `sentinel/crdt/dots.py`

`Dot` and `DotContext`. The methods that matter: `contains`, `add`, `next_dot` (take the next dot for this node and record it), `merge`, `compact`, `covers`, and the wire form (`to_wire`, `from_wire`), which is a sorted version vector and a sorted cloud.

Easy to get wrong: `dots()` enumerates every dot a context names. It is fine for your own context in a test. Never call it on a context a peer sent. `covers` exists so that nothing on the exchange path has to.

### `sentinel/crdt/mvmap.py`

`Register` (store and context) and `MVMap`. `write` takes a fresh dot from the map-wide context, and the new value replaces every value the register held. `read` returns every visible `(dot, value)`, and `conflicted` is simply "more than one". `merge_register` implements the join above and returns whether anything changed, which is how the service knows what to save. `missing_for(peer)` returns every register whose context the peer's context does not cover. `state_digest` hashes the visible values only, so two replicas that show the same thing have the same digest.

Easy to get wrong: there are two contexts. Each register's `ctx` decides every merge for that key. The map-wide `MVMap.ctx` only issues fresh dots and tells peers what this replica has seen. Mixing them up breaks the join.

### `sentinel/crdt/codec.py`

`encode` is canonical CBOR, `digest` is the sha256 of that, and `decode` returns `Any`. The caller must check the shape it expected, because wire data is untrusted.

### `sentinel/crdt/signing.py`

`NodeKey.load_or_create` makes an Ed25519 key on first use and writes it as PEM with mode 0600. `TrustStore.verify` returns `False` for an unknown node or a bad signature. It never raises, so a bad entry is a rejection, not a crash.

### `sentinel/crdt/log.py`

`Entry` is the frozen record. `unsigned()` is what gets signed, `signed_bytes()` is its canonical encoding, and `digest()` hashes the full wire form, signature included. `SignedLog` holds the entries, the log's context, a Lamport counter and the rejections.

- `append` refuses a kind outside `KINDS` and refuses to author without a key. It then takes the next dot, links `prev` to this node's previous entry and signs.
- `verify` turns a signature that is not hex into `False`, not an exception.
- `merge` does four steps per entry, in this order:
  1. an entry already held, byte for byte, is skipped;
  2. an entry whose signature does not verify is rejected and recorded;
  3. a validly signed entry at a held dot with a different digest raises `IntegrityError`;
  4. the hash chain is checked against whichever neighbours are held, then the entry is accepted.
- `_reject` records a rejection once per `(dot, digest)`, keeps the newest `REJECTIONS_KEPT` (1,000), and does **not** add the dot to the context.
- `missing_for`, `ordered` and `state_digest` serve the exchange and the views.

Easy to get wrong: the order of steps 2 and 3. Compare digests first and an unsigned forgery that reuses a held dot raises `IntegrityError`, so anyone on the link can make a replica stop. Verifying first means only a validly signed conflict can do that: a bug in a trusted node, or a stolen key. `tests/test_ops_hostile_peer.py::test_a_forgery_that_reuses_a_dot_is_rejected_and_recorded_not_raised` holds this.

The docstring of `_reject` explains why a rejected dot stays unseen. There are three reasons:

- A peer never offers a dot your context claims. Mark a rejected entry as seen, and an entry from a node you trust later is lost to you for good.
- Anyone can forge an entry at any dot. Mark forged dots as seen, and a forgery keeps the genuine entry out.
- The context must stay "the entries held", because the service rebuilds it from them on restart.

The price is that the peer resends the entry on every exchange. That is why rejections are keyed and bounded rather than appended.

### `sentinel/ops/service.py`

`OpsService` is the replica a node runs. It is mission-agnostic: event ids are opaque strings.

- **Persistence.** Three SQLite tables: `ops_entries`, `ops_registers` and `ops_peers`. `_load` rebuilds the log, the registers and both contexts at start.
- **`append`** accepts only `ENTRY_KINDS` (`DECISION`, `NOTE`, `RESOLUTION`). The log also admits `AI_DRAFT_CONFIRMED`, but nothing writes it: a confirmed AI draft becomes a DECISION that carries its provenance (chapter 11). The entry's `event_ref` is the event id plus whatever `current_ref(event_id)` returns.
- **`annotate`** checks the field and, for `triage_status`, the value. It stores `{"v", "by", "node", "at"}` in the register. If the write replaced more than one value, it also appends a signed RESOLUTION whose body names the field, the new value and every value superseded (`tests/test_ops_log.py`).
- **Views.** `_entry_view` adds `signature_valid` (re-verified now, against the current trust store) and `review_required`. `annotations`, `conflicts` and `digest` feed the API: `GET /api/events/{event_id}/ops` and `GET /api/ops/digest` in `sentinel/api/app.py`. The console renders them in `web/src/components/OpsPanel.tsx`.
- **Anti-entropy.** `contexts`, `payload_for`, `merge_payload`, `peer_contexts` and `remember_peer`.
- **`load_identity`** loads or creates the key at `<var>/keys/<node_id>.ed25519.pem`, reads `SENTINEL_TRUST_FILE`, and adds the node's own key when that file does not list the node. `harness/identity.py` enrols nodes into one trust file the same way.

Easy to get wrong: `_merge_entries`. It decodes every entry before merging any, so a malformed payload merges nothing. Its `finally` block saves whatever the merge accepted before an `IntegrityError`. Peers learn this replica's context from memory and never resend what it claims to hold, so memory and disk must agree even after a failure.

#### REVIEW_REQUIRED

A decision is made against a specific CDM. The service cannot know about CDMs (`.importlinter` forbids `sentinel.ops` from importing any mission module), so the conjunction module passes in a callback, `ConjunctionService.current_ref` in `sentinel/conjunction/service.py`:

- if the node holds a CDM for the event, the callback returns the latest one's full sha256, inputs hash and message id;
- if the event is known only from the hub's summary, it returns the record the hub asserted, which is the 16-hex-digit prefix the summary carries.

`_entry_view` flags a DECISION `review_required` when the current reference is a different record from the one the decision names. `same_record` compares them as prefixes either way round. So a decision made on a summary is not flagged when the very CDM the summary named arrives, and is flagged when a different one does (`tests/sync/test_decisions_on_summaries.py`). The flag is computed when the entry is read, on each node, and never replicated. Two nodes can disagree about it until they hold the same CDMs.

### `sentinel/sync/operator_data.py` and the exchange

`OperatorData` is a protocol: the five methods sync needs. Sync passes contexts and payloads through without reading inside them. The exchange is one request/reply on `ops.<hub_id>.exchange`, run first in every cycle (`SyncAgent.exchange_ops` in `sentinel/sync/agent.py`, `SyncServer._ops` in `sentinel/sync/server.py`):

```
edge                                                   hub
peer = remembered hub contexts (may be stale)
push = payload_for(peer, budget)
request {from, log_ctx, mv_ctx, push, budget}  ---->   merge_payload(push)
                                                       pull = payload_for(edge's contexts, budget)
                                   <----  reply {pull, ctx, merged}
merge_payload(pull)
remember_peer(hub, ctx)
```

The two sides differ. The hub builds its pull from the contexts in the request, which are fresh. The edge builds its push from a memory of the hub, which may be stale. Stale is safe: it only means sending something the hub already holds, and merge is idempotent. A lost reply just means the next cycle sends the same push again.

The **budget** is what the measured link moves in 10 s (`OPS_BUDGET_S`), at most 256,000 bytes, each way. `payload_for` lists log entries in display order, then registers by key, and `_leading_within` keeps the leading items that fit, always at least one. Nothing is lost: an item's dots enter the peer's context only when that item is merged there. `reply_budget` answers a missing or unreadable budget with everything, as before budgets existed. `tests/test_ops_thin_link.py` shows a 60-entry backlog draining over a link the old single reply could not cross.

## Try it

Everything below runs on this machine, and none of it touches the demo on :8000 and :8001.

**Dots, the cloud and `covers`.** Start `uv run python` at the repository root:

```python
>>> from sentinel.crdt import Dot, DotContext
>>> ctx = DotContext()
>>> ctx.add(Dot("edge-alpha", 1)); ctx.add(Dot("edge-alpha", 3))
>>> ctx
DotContext(vv={'edge-alpha': 1}, cloud=[Dot(node='edge-alpha', seq=3)])
>>> ctx.add(Dot("edge-alpha", 2)); ctx
DotContext(vv={'edge-alpha': 3}, cloud=[])
>>> DotContext({"edge-alpha": 3}).covers(DotContext({"edge-alpha": 10**9}))
False
```

Look for dot 3 waiting in the cloud until dot 2 fills the gap. The last line answers at once: nothing enumerated a billion dots.

**A conflict and its resolution.** In the same session:

```python
>>> from sentinel.crdt import MVMap
>>> hub, edge = MVMap("hub"), MVMap("edge-alpha")
>>> hub.write("EV1|triage_status", "WATCH"); edge.write("EV1|triage_status", "MANEUVER_PLANNING")
Dot(node='hub', seq=1)
Dot(node='edge-alpha', seq=1)
>>> [hub.merge_register(k, r) for k, r in edge.missing_for(hub.ctx).items()]
[True]
>>> hub.read("EV1|triage_status")
[(Dot(node='edge-alpha', seq=1), 'MANEUVER_PLANNING'), (Dot(node='hub', seq=1), 'WATCH')]
>>> hub.write("EV1|triage_status", "MANEUVER_PLANNING"); hub.read("EV1|triage_status")
Dot(node='hub', seq=2)
[(Dot(node='hub', seq=2), 'MANEUVER_PLANNING')]
>>> [edge.merge_register(k, r) for k, r in hub.missing_for(edge.ctx).items()]
[True]
>>> edge.read("EV1|triage_status"), hub.state_digest() == edge.state_digest()
([(Dot(node='hub', seq=2), 'MANEUVER_PLANNING')], True)
```

`write` returns the dot it took, and `merge_register` returns whether anything changed. Two values after the first merge is the CONFLICT. After the hub's write, which had seen both, the edge's old value is gone on both sides.

**Forgery, rejection and late trust.**

```python
>>> import dataclasses
>>> from sentinel.crdt import NodeKey, SignedLog, TrustStore
>>> keys = {n: NodeKey.generate(n) for n in ("hub", "edge-alpha")}
>>> trust = TrustStore({n: k.public_hex() for n, k in keys.items()})
>>> edge_log, hub_log = SignedLog("edge-alpha", keys["edge-alpha"], trust), SignedLog("hub", keys["hub"], trust)
>>> e1 = edge_log.append("DECISION", {"decision": "MONITOR"}, {"event_id": "EV1"}, "maj.ortiz", "2026-09-24T06:00:00+00:00")
>>> e2 = edge_log.append("NOTE", {"text": "Pc rising"}, {"event_id": "EV1"}, "maj.ortiz", "2026-09-24T06:05:00+00:00")
>>> e2.prev == e1.digest()
True
>>> forged = dataclasses.replace(e1, body={"decision": "MANEUVER"})
>>> hub_log.merge([forged, forged]), hub_log.rejected, hub_log.ctx.contains(e1.dot)
([], [{'dot': ['edge-alpha', 1], 'reason': 'untrusted-or-bad-signature', 'author': 'maj.ortiz'}], False)
>>> [e.dot.seq for e in hub_log.merge([e2, e1])], hub_log.state_digest() == edge_log.state_digest()
([2, 1], True)
```

Look for three things. The forgery offered twice is recorded once. Its dot is still unseen, so the genuine entry still gets in. Entries arriving out of order merge, because the chain is checked only against neighbours already held. To see late trust, make a log that trusts only itself, merge `e1` (rejected), call `.trust.add("edge-alpha", keys["edge-alpha"].public_hex())` on it, and merge `e1` again: it is accepted.

**The tests.**

```bash
uv run pytest -q -rxX tests/property/test_crdt.py tests/test_ops_log.py tests/test_ops_hostile_peer.py tests/test_ops_thin_link.py
```

Expect everything to pass except one strict xfail, `test_an_untrusted_peer_cannot_erase_an_annotation`, printed with its reason. That is the open gap below. Add `--hypothesis-show-statistics` to see the stateful model run 150 random histories.

**Break it on purpose.** Save this as `/tmp/lww_mutant.py`. It swaps the register join for last-writer-wins in memory only, and runs the property test:

```python
import sys
import pytest
from sentinel.crdt import mvmap

real = mvmap.MVMap.merge_register

def last_writer_wins(self, key, other):
    changed = real(self, key, other)
    reg = self.registers[key]
    if len(reg.store) > 1:
        newest = max(reg.store, key=lambda d: (d.seq, d.node))
        reg.store = {newest: reg.store[newest]}
    return changed

mvmap.MVMap.merge_register = last_writer_wins
property_tests = "tests/property/test_crdt.py"
sys.exit(pytest.main([property_tests, "-q", "-x", "-p", "no:cacheprovider"]))
```

Run it from the repository root with `uv run python /tmp/lww_mutant.py`. Hypothesis fails and shrinks the history to a few steps: two nodes write the same key, everyone syncs, and one write is missing. The replicas still converge. What fails is the "no silent overwrite" invariant, which is exactly what LWW gives up.

**Your own hub and edge.** After `make tools`, start `uv run python` at the repository root. `Cluster` picks free ports, so it never touches the demo:

```python
from harness.cluster import Cluster, http, wait_until
c = Cluster(hub_exercise=True).start()
wait_until(c.leaf_connected, 20)
ev = wait_until(lambda: http("GET", f"{c.edge}/api/events?scope=active"), 60)[0]["event_id"]
c.link("DENIED")
http("POST", f"{c.edge}/api/events/{ev}/annotation", {"field": "triage_status", "value": "MANEUVER_PLANNING"}, {"X-Sentinel-Operator": "maj.ortiz@edge-alpha"})
http("POST", f"{c.hub}/api/events/{ev}/annotation", {"field": "triage_status", "value": "WATCH"}, {"X-Sentinel-Operator": "capt.lee@hub"})
c.link("CONNECTED")
http("GET", f"{c.edge}/api/ops/digest")          # repeat until "conflicts" names the event
http("POST", f"{c.hub}/api/events/{ev}/annotation", {"field": "triage_status", "value": "MANEUVER_PLANNING"}, {"X-Sentinel-Operator": "col.reyes@hub"})
http("GET", f"{c.edge}/api/events/{ev}/ops")["entries"]   # a few seconds later
c.stop()
```

In the digest, look for `conflicts` naming the event and `mv_vv` holding both nodes. On the event's ops, `annotations.triage_status.values` first holds both values, each with `by` and `node`. After the resolution, the edge's entries include a RESOLUTION authored by `col.reyes@hub`, node `hub`, with `signature_valid: true` and both overruled values under `body.superseded`. The digests, dots and times differ on every run.

## Design choices

Each is recorded in [ADR-005](../system-design.md#adr-005--state-based-crdts-for-operator-generated-data) unless another ADR is named.

- **State-based CRDTs, not operation-based.** Buys: any delivery order, duplicates and losses are harmless, so the exchange needs no acknowledgements or retransmission log. Costs: dots, contexts and anti-entropy to maintain, and state rather than operations on the wire (bounded by contexts and the budget). Rejected: operation-based CRDTs, which assume reliable causal delivery that a DDIL link does not give.
- **Multi-value registers, not last-writer-wins.** Buys: no silent loss, and a disagreement shown to people who can settle it. Costs: an operator has to resolve a CONFLICT. Rejected: LWW, which destroys work, and a manual merge screen, which moves the problem to the operator at the worst moment. Here nothing is lost while a CONFLICT waits.
- **A signed, hash-chained log for decisions.** Buys: a record that cannot be altered on the link without detection, bound to the node that wrote it. Costs: key management and trust files. It proves which node, not which person (`SECURITY.md`, gap 1).
- **Registers are not signed.** Buys: simplicity. Costs: the open gap below. Until it closes, the log is the record of what was decided.
- **Reject, and resend, rather than mark as seen.** Buys: an entry merges once its node is trusted, and a forgery cannot suppress a genuine entry. Costs: a rejected entry crosses the link on every exchange.
- **Stop on a validly signed conflict.** Buys: the replica never chooses which of two signed histories to believe. Costs: availability, described under "How it fails".
- **Operator data rides the sync cycle, first, within a budget** ([ADR-008](../system-design.md#adr-008--reference-data-application-level-priority-pull-not-transport-replication) for the cycle, [ADR-004](../system-design.md#adr-004--modular-monolith-with-an-internal-event-bus) for why not JetStream). Buys: a backlog never starves the manifest and records, and the durable SQLite state does its own store-and-forward. Costs: a large backlog takes several cycles.
- **REVIEW_REQUIRED through a callback.** Buys: `sentinel/ops` stays mission-agnostic, which `.importlinter` enforces, and no derived state is replicated. Costs: each node computes the flag from the CDMs it holds, so nodes can disagree for a while.

## How it fails

- **A tampered or forged entry.** Rejected before merge, recorded once in `rejected` (shown in `GET /api/ops/digest`), and resent by its peer. A signature that is not even hex is treated the same way.
- **An author the replica does not trust.** Also rejected, because trust is incomplete, not wrong. The trust file is read at start. Add the key, restart, and the next exchange merges the resent entries. The technical guide's troubleshooting table names the symptom: decisions from another node never appear.
- **The resend has a cost.** Rejected entries are old, so they sort first in every budgeted payload. If they alone exceed the budget, nothing newer crosses in that direction until the trust stores agree. No test covers this case yet.
- **A validly signed entry at a held dot with different content**, or a hash-chain break with both neighbours present. `IntegrityError`. Whatever the merge accepted before that point is saved. The exchange runs first in the sync cycle, so the error ends the whole cycle: no manifest and no records that cycle. The link monitor counts a failure each cycle, so the edge's link state degrades and, after 8 s, reads DENIED, although the link is up. The edge logs `Sync cycle failed`; when the hub is the side that raised, it also logs `Responder failed`. One realistic cause is a node that lost its database but kept its key: it numbers its writes from 1 again.
- **A malformed payload.** Every entry is decoded before any is merged, so nothing merges. The request fails.
- **A register this node could not show**: an unknown key, a value that is not an annotation, or an unknown triage status. Dropped, with a `Peer register rejected` warning that names the key and the reason. The rest of the payload merges.
- **A lost reply, or a stale memory of the peer.** More bytes next cycle, nothing else.
- **A thin link.** Each exchange carries at most its budget each way, and a backlog drains over several cycles.
- **A database edited on disk.** `_load` does not verify, but every view re-verifies. The entry shows `signature_valid: false`, the console marks it with a cross instead of "signed", and peers reject it if it is offered.
- **The open gap: registers are unsigned** (`SECURITY.md`, gap 4). A register carries its context and no signature. A peer that can reach `ops.<hub_id>.exchange` can send an empty register whose context claims `{hub: 1000}`. By the join rule, the hub's value was "seen and dropped", so it is erased, and the hub passes that to every edge as an ordinary overwrite. `tests/test_ops_hostile_peer.py::test_an_untrusted_peer_cannot_erase_an_annotation` records it as a strict xfail, and `test_mvmap_keeps_what_the_peer_never_saw` is the control. The claimed history also lands in the hub's `mv_vv`, where `GET /api/ops/digest` shows it. The same trick fails against the log, because a log entry merges only with a valid signature. Closing the gap is a design change for ADR-005: sign registers, or authenticate peers on the leaf link (gap 2).

## Check yourself

1. The hub rejects an entry from an untrusted edge. Why not add its dot to the hub's context, which would stop the edge resending it?

   <details><summary>Answer</summary>A peer never offers a dot the context claims. So the entry would never arrive again, even after the edge's key is trusted. And since anyone can forge an entry at any dot, marking forged dots as seen would let a forgery keep the genuine entry out for good. The context also has to mean "entries held", because it is rebuilt from them on restart. The cost is a resend each exchange, so rejections are recorded once per (dot, digest) and bounded.</details>

2. Register `K` at the hub has store `{(hub,2): X}` and context `{hub:2, alpha:1}`. A delayed payload from alpha arrives with store `{(alpha,1): Y}` and context `{alpha:1}`. What does the hub show afterwards, and why?

   <details><summary>Answer</summary>Only X. `(alpha,1)` is in the hub's context but not its store, so the hub has seen it and it was overwritten: the join drops it. `(hub,2)` is not in alpha's context, so it survives. No CONFLICT.</details>

3. Why does `SignedLog.merge` verify the signature before comparing digests at a held dot?

   <details><summary>Answer</summary>Otherwise an unsigned forgery that reuses a held dot looks like "same dot, different content" and raises `IntegrityError`, so anyone who can reach the exchange can make the replica stop. Verifying first turns a forgery into a recorded rejection. Only a validly signed conflict, which means a trusted node's bug or a stolen key, can stop it.</details>

4. `covers` returns `False` for `{alpha: 3}` against `{alpha: 5}` without listing dots 4 and 5. What invariant makes that safe, and what attack does it prevent?

   <details><summary>Answer</summary>`compact` never leaves the dot right after a node's prefix in the cloud; it would be folded in. So a longer prefix on the other side always includes a dot this side lacks. Not enumerating keeps the cost at the size of the context as sent, so a peer claiming `{alpha: 10**9}` cannot make the hub build a billion dots on every exchange.</details>

5. An edge operator records a decision on an event the edge knows only from the hub's summary. Later the full CDM the summary named arrives. Then a newer CDM arrives. When is the decision REVIEW_REQUIRED?

   <details><summary>Answer</summary>Only after the newer CDM. The decision names the summary's 16-hex-digit prefix, and `same_record` matches a prefix against the full sha256 of the CDM it named, so the first arrival is the same record. The newer CDM is a different record, so the flag appears. It is computed on read, on each node.</details>

6. Replace the register join with last-writer-wins. The replicas still converge. Which property test fails, and what does that tell you about "convergence" as a goal?

   <details><summary>Answer</summary>The "no silent overwrite" check in `converge`: a write that nobody overwrote knowingly is missing. Convergence alone is easy (LWW has it). The property that matters is that everything anyone wrote is either visible or was replaced by someone who had seen it.</details>

7. The hub's reply to an exchange is lost after the hub merged the edge's push. What happens next cycle? Can an entry be duplicated?

   <details><summary>Answer</summary>The edge never updated its memory of the hub's context, so it sends the same push again. The hub skips every entry it already holds byte for byte and every register the join leaves unchanged. The log is a map keyed by dot, so nothing can be duplicated. The cost is bytes.</details>

8. Someone on the leaf link sends an empty `EV1|triage_status` register with context `{hub: 1000}`. What happens, and why would the same trick against the decision log fail?

   <details><summary>Answer</summary>The hub's value is in the claimed context but not in the store, so the join treats it as overwritten and erases it, then passes that on to the edges. That is gap 4, held by a strict xfail. Log entries are merged only when their signature verifies under a trusted key, and a context alone never removes an entry, because the log is grow-only.</details>

## Where next

- [9. The DDIL harness](09-ddil-harness.md) runs this on real processes. DENIED makes the CONFLICT and the REVIEW_REQUIRED flag happen over a real cut link.
- [7. Priority sync](07-priority-sync.md) covers the rest of the cycle this exchange runs first in.
- [5. The operator console](05-console.md) shows how `OpsPanel` renders conflicts, signatures and REVIEW REQUIRED.
- [11. The AI assistant](11-ai-assistant.md) turns a confirmed draft into a signed DECISION, and refuses one made on a superseded CDM.
- Reference: ADR-005 in [`docs/system-design.md`](../system-design.md), gaps 1, 2 and 4 in [`SECURITY.md`](../../SECURITY.md), "Operator data: CRDTs" in [`docs/technical-guide.md`](../technical-guide.md), and the `ops.<hub_id>.exchange` row in [`docs/icd/sync-envelope.md`](../icd/sync-envelope.md).
