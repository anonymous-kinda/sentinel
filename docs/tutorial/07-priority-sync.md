# 7. Priority sync

## What you will learn

- How one sync cycle runs: operator data, then the manifest, then full records in priority order.
- How the edge decides what to fetch first (class, then earliest deadline) and what it refuses to spend the link on (admission control, SUMMARY-ONLY).
- What the edge checks before it admits a fetched record, and what VERIFIED, HUB_ASSERTED, UPDATING, MISMATCH and LOCAL each promise.
- How a mission module plugs into sync without a line of `sentinel/sync` changing, and how the repository proves it.
- How every wait and every budget is sized from the link the edge has measured.

## Why it exists

After a denial, or on a link of a few kilobits a second, the hub holds more
than the edge can fetch quickly. The edge operator needs three things, in this
order:

1. **The whole picture at once.** Every active event, even before any full CDM
   has arrived, clearly marked as the hub's claim.
2. **The most urgent full record first.** The event whose maneuver commit point
   comes soonest must not wait behind history or routine data.
3. **Numbers the edge has checked.** An edge that shows the hub's Pc as its own
   hides the one thing a DDIL design must never hide: what this node actually
   computed.

A transport mirror delivers records in the order they arrived, and trusts
them. The sync layer is Sentinel's own answer to all three.
`docs/ddil-results.md` holds the measured difference between this order and
arrival order on the same link.

## Concepts

### Two kinds of data, two flows

**Reference data** (CDMs, element sets) is created upstream and flows one way:
the edge pulls it from the hub. **Operator data** (decisions, notes, triage
annotations) is created on any node and flows both ways as CRDT state
(chapter 8). Both ride request/reply over the leaf link, on the three subjects
from chapter 6. The hub only answers. The edge's `SyncAgent` asks, every
`SENTINEL_SYNC_INTERVAL_S` seconds (2 by default).

### Records, summaries and the manifest

A **record** is opaque bytes: a CDM's KVN text, or an element set's JSON. It is
named by the first 16 hex digits of its sha256, its **sha16**. Naming by
content means the name also checks the bytes.

A **summary** describes one item (a conjunction event, or one object's element
set). Sync reads four fields of it and nothing else:

| Field | Meaning |
|---|---|
| `e` | item id, such as an event id or `omm:25544` |
| `dl` | deadline, epoch seconds. For a conjunction, the maneuver commit point (MCP): TCA minus the operator's lead time, 8 h by default. For an element set, the moment it goes stale. |
| `q` | consequence, 0 (ROUTINE) to 3 (CRITICAL) |
| `c` | the item's records, oldest first: `[sha16, bytes, created_epoch]` |

The conjunction module adds its own fields (band, Pc in log10, miss distance
and more) so the edge can show the event before its CDM arrives. The
**manifest** is the list of every summary the hub offers, encoded as canonical
CBOR. Its sha256 is the manifest **digest**. The edge sends back the digest it
last applied, and the hub answers "unchanged" with an empty body when nothing
moved.

### One cycle

```
edge SyncAgent.cycle()                                hub SyncServer
 1. ops exchange   contexts + push (budgeted)  ---->  merge push
                   pull (budgeted) + hub ctx  <----   payload_for(edge ctx)
 2. manifest       {known: last digest}        ---->  digest == known ?
                   summaries, or "unchanged"  <----
    apply          store summaries, rebuild the want-list, remember the digest
 3. pull           for each wanted record, in priority order:
                     SUMMARY_ONLY if it cannot arrive before its deadline
                   {sha: sha16}                ---->  records.get(sha16)
                   original bytes + headers   <----
                     check the hash, file under the manifest's item, ingest
```

Operator data goes first. It is small, it is P0, and on a denied link it
fails first, which ends the cycle before the manifest wait can grow.

### The want-list and its order

The want-list is a **set difference**: every record the manifest names, minus
the records this node already holds. Each wanted record gets a class:

| Class | Which records |
|---|---|
| `P1_URGENT` | the latest record of an item with consequence SERIOUS or worse, due within the urgent window (72 h) |
| `P2_ROUTINE` | any other latest record, element sets included |
| `P4_BULK` | superseded records, the item's history |

`P0_SUMMARY` needs no queue: the ops exchange and the manifest run before any
record. `P3_REFERENCE` is defined but nothing uses it yet. Records are
ordered by class, then by **earliest deadline first** (EDF), then by higher
consequence, then by item id.

Why EDF? When jobs wait for one server that does them one at a time, deadline
order minimises the worst lateness: if any order finishes every job on time,
deadline order does too. The repository cites Liu and Layland (1973). Their
theorem is about periodic, preemptible tasks; the closer classical result for
a one-off backlog is Jackson's earliest-due-date rule. Either way, the scarce
link goes to whatever expires first. Class still comes first, so a routine
record due in an hour waits behind an urgent one due tomorrow. Sync does not
judge urgency itself: the module supplies the consequence and the deadline.

### Admission control

Before fetching the latest record of an item, the agent asks whether it can
arrive in time. The link monitor (chapter 6) predicts the transfer in wall
seconds, and the node clock may run faster than the wall clock in a
simulation, so the check is:

```
eta_wall     = size / measured_rate + rtt
seconds_left = deadline - clock.now()        (read now, for this record)
if eta_wall * clock.scale > seconds_left:    hold the item SUMMARY_ONLY, spend nothing
```

The clock is read per record, because the fetches ahead of it in the same pull
spent real time. With no rate measured yet, there is no ETA and no holding.
History records and FIFO mode are never held.

### Verification states

The edge re-assesses every fetched CDM with its own engine and compares the
result with what the hub's summary asserted:

```
hub summary here, no CDM of the event here            HUB_ASSERTED  the hub's numbers, marked as such
some CDMs here, but not the hub's latest              UPDATING      this node's numbers, for an older CDM
the hub's latest here, re-assessed here, and
    every result field equal to the hub's claim       VERIFIED
    any result field different                        MISMATCH      flagged and logged
no hub summary, or a CDM newer than any it listed     LOCAL         this node's own data
```

"Every result field" means the inputs hash, the method (a refusal reason or
none), the band and worst-case band, the Pc and max Pc, the dilution flag, the
miss distance and the relative speed. Each is compared at the precision the
summary carries it, so float noise does not flag, but a different engine
version, configuration or bug does.

### Timeouts and budgets from the measured link

Every wait is sized from the measured rate `r`, taken as 1,000 B/s until one is
measured and never below 400 B/s:

```
timeout(bytes)     = 6 s + 1.5 * bytes / r
record             bytes = its size in the manifest
manifest           bytes = size of the last manifest (at least 4,000), doubled per timeout in a row, at most 256 KiB
ops exchange       bytes = request + budget + 2,000;   budget = min(r * 10 s, 256,000) each way
pull               at most max(5 * interval, 10 s) of fetching per cycle
```

## Code walkthrough

Read the files in this order: the two interfaces, the server, the ordering,
the agent, then the modules that plug in.

### `sentinel/sync/records.py`: `ReferenceRecords`

The whole contract between sync and a mission module is five methods:
`manifest()`, `get(sha16)`, `has(sha16)`, `put_summaries(summaries, origin)`
and `async ingest(raw, source, data_class, item_id)`. Sync never learns what a
record means. `.importlinter` (the `sync-is-mission-agnostic` contract)
forbids `sentinel.sync` to import any mission module or the API.

*Easy to get wrong:* `has` decides the set difference. A module whose `has`
answers only for records it *admitted* will see a rejected record fetched
again, as How it fails shows.

### `sentinel/sync/operator_data.py`: `OperatorData`

The five methods sync needs from the operator-data replica: `contexts`,
`peer_contexts`, `remember_peer`, `payload_for` (optionally within a byte
budget) and `merge_payload`. Contexts and payloads are CRDT wire data that sync
passes through unread. Chapter 8 covers `sentinel.ops.OpsService`, which
implements it.

### `sentinel/sync/server.py`: `SyncServer`

`start` serves the three subjects. `_manifest` builds the manifest, computes
`codec.digest` of it, and if the request's `known` equals the digest, returns
an empty body with `Sentinel-Unchanged: 1`. Otherwise it returns the CBOR body
with `Sentinel-Digest` and `Sentinel-Schema`. `_fetch` returns the record's
original bytes with its module's headers plus `Sentinel-Kind: record.full`,
or `Sentinel-Error: not-found`. `_ops` merges the edge's push first, then
replies with what the edge lacks, within `reply_budget(request["budget"])`,
and the hub's contexts. `requests` counts each kind for `GET /api/sync`.

*Easy to get wrong:* "unchanged" saves the link, not the hub. The hub still
builds and hashes the whole manifest for every request. The conjunction module
caches its part per store version (`ConjunctionService.manifest`) because every
edge asks every cycle.

### `sentinel/triage/__init__.py`: the order

`Consequence`, `PriorityClass` and the frozen `TriageKey`. `TriageKey.sort_key`
is `(class, deadline or far future, -consequence, item_id)`, and `order` sorts
by it. The module never mentions a conjunction.

*Easy to get wrong:* `triage_key` in `sentinel/conjunction/policy.py` computes
a class the same way, but nothing calls it. The agent assigns classes itself
in `SyncAgent._wanted`. Editing `triage_key` changes nothing.

### `sentinel/sync/agent.py`: `SyncAgent`

Read it in cycle order.

**`run` and `cycle`.** `run` loops forever. A link error (`RequestTimeout`,
`NoResponders`, `ConnectionError`, `OSError`) ends the cycle, calls
`link.observe_failure()`, and records `{error, at}` as `last_cycle`. Any other
exception is logged as `Sync cycle failed` and also counted as a failure, so
the agent outlives any single bug. After each cycle it publishes `link.state`
when the measured state changed, and `sync.progress` always. `cycle` calls
`exchange_ops`, `fetch_manifest`, `apply_manifest` when the manifest changed,
and `pull`.

**`exchange_ops` and `_ops_budget`.** The push is what the hub was last known
to lack (`peer_contexts`), held to the budget. The reply's `pull` is merged,
and the hub's contexts are remembered for the next push. Both directions share
one round trip, and its bytes feed the link monitor.

**`fetch_manifest` and `_manifest_expected_bytes`.** The request carries
`known`, the digest of the last manifest *applied*. A timeout increments
`_manifests_lost`, logs `Manifest request timed out` with the expected sizes,
and re-raises. A reply resets it. An unchanged reply returns `None`. A body
records its size, for the next wait, and its digest.

**`apply_manifest`, `_rebuild_queue`, `read_summary` and `_wanted`.**
`apply_manifest` hands every summary to the module (`put_summaries`), rebuilds
the queue, and only then sets `manifest_digest`. `read_summary` checks the
four generic fields and raises one of `MALFORMED` if it cannot read them.
`_rebuild_queue` skips such an entry with `Manifest entry skipped` and keeps
going. `_wanted` turns one summary into `WantItem`s: records `has` says are
missing, classed as in Concepts. The queue is then sorted with `order`, or by
`(created, sha16)` in FIFO mode, and `RetryBackoff.retain` forgets back-off
state for records no longer wanted.

*Easy to get wrong:* the queue is rebuilt only when the manifest changes. A
class is fixed at that moment. An item that enters the 72 h window later stays
`P2_ROUTINE` until the hub's manifest next changes.

**`pull`.** It walks the queue in order. It skips arrived records and records
still sitting out a back-off. It computes the ETA and applies admission
control, and it stops once the pull budget is spent. A held record is marked
`SUMMARY_ONLY` and its item added to `summary_only`. That is not final: the
record stays in the queue and is re-judged every pull. At the end, arrived
records leave the queue.

*Easy to get wrong:* the budget check comes after admission control and
before each fetch, so one long fetch can overrun it. The budget stops the
*next* fetch, not the current one.

**`_fetch` and its helpers.** `_request_record` asks for the sha16 with a
timeout sized from the record's manifest size, and reports the round trip to
the link monitor whatever the reply says. Then:

1. `Sentinel-Error` on the reply puts the record back as `QUEUED`.
2. `_is_the_record_asked_for` hashes the bytes. The sha256 must begin with the
   sha16 the manifest named *and* equal the hub's `Sentinel-Sha256` header. A
   missing header is not a match. Failing that is refused as `hash_mismatch`.
3. `Sentinel-Event-Id`, if sent, must equal the manifest's item id, or the
   reply is refused as `item_id_mismatch`.
4. `records.ingest(raw, "sync:<hub_id>", data class, item.event_id)` admits it
   under the item the manifest named. The edge never re-derives an event's
   identity, or updates fetched out of order would split one event into two.
5. An exception from `ingest` is logged as `Sync record ingest failed`, and the
   record is put back.

`_refuse` and `_put_back` re-queue a record and ask `RetryBackoff.failed` how
many pulls it must sit out: 1, then 2, 4, 8, 16, and at most 32. `_arrived`
clears the back-off, clears SUMMARY-ONLY for the item, and publishes
`sync.arrival`, whose `hash_ok` is therefore always true.

**`status`.** It returns the view `GET /api/sync` serves: mode, link snapshot,
queue (each item's class, deadline, status and ETA), the last 50 arrivals, the
total, the items held summary-only, and `last_cycle`.

### `sentinel/conjunction/summaries.py`: what a conjunction summary says

`compact_summary` builds the wire summary from an event summary: the four
generic fields plus `p`, `s`, `t`, `b`, `w`, `pc` and `px` (log10, 3
decimals), `d`, `r`, `md`, `rs`, `h` and `dc`. `SUMMARY_MAX_BYTES` (256) is the
bound `tests/sync/test_hub_edge.py` holds every exercise summary to, less its
record list. `RESULT_FIELDS` and `disagreements` implement the comparison:
this node's result is encoded by the same `compact_summary`, then compared
field by field. `expand_summary` turns a hub summary back into the API's event
shape with `verification: HUB_ASSERTED` and `asserted_by`. `summary_problem`
refuses a summary this node could not display, for example a probability
outside [0, 1]. `voice_line` renders one line that can be read over a voice
net.

*Easy to get wrong:* comparing raw floats. Both sides go through the same
encoding, so the comparison happens at the precision the wire carries.

### `sentinel/conjunction/sync_adapter.py` and the service behind it

`ConjunctionRecords` implements `ReferenceRecords` over `ConjunctionService`:

- `get` finds a CDM by prefix and returns its bytes with `Sentinel-Sha256`,
  `Sentinel-Event-Id`, `Sentinel-Data-Class` and `Nats-Msg-Id`.
- `put_summaries` stores each summary as the hub's assertion, or logs
  `Hub summary rejected` with the reason from `summary_problem`.
- `ingest` passes `event_id=item_id` to `ConjunctionService.ingest`, then asks
  `ConjunctionService._verification` for the state. On a MISMATCH for the
  event's latest CDM, it logs `Hub assertion not reproduced` with the fields
  that differ.

In `sentinel/conjunction/service.py`, `manifest` serves the active events
(TCA still ahead) from a list cached per store version. `_offered_events`
offers only events whose verification is LOCAL, so a node never re-serves
another node's assertions. `list_events` adds the HUB_ASSERTED events known
only from summaries, and `_verification` implements the states from Concepts.

### `sentinel/passes/sync_adapter.py`: element sets over the same agent

`ElementRecords` offers one summary per element set: `e` is `omm:<NORAD id>`,
`dl` is the element epoch plus three days (when it goes stale), `q` is
ROUTINE, and `c` holds one record. `offered` limits the manifest to the imaging
catalog unless `SENTINEL_SYNC_ELEMENTS=all`, because every record costs a round
trip (ADR-008, "Reference data on a thin link"). `ingest` adds the set to the
`ElementStore`, and on acceptance awaits the hook that makes the pass module
publish `passes.updated`. Element sets have no verification state (`None`).
The unit and its pass windows are not records, so they never enter a manifest.

### `sentinel/api/records.py`: `CompositeRecords`

The sync layer takes one `ReferenceRecords`. `CompositeRecords` puts several
behind it. It concatenates their manifests and asks each in turn for `get` and
`has`, after checking the sha16 is hex (so `%` or an empty string can never
act as a pattern). It routes `put_summaries` and `ingest` by item-id prefix,
with the conjunction module as the default. `_sync_records` in
`sentinel/api/app.py` assembles it, which is why a new module touches the
assembly layer and never `sentinel/sync`.

## Try it

**1. The running demo, read only.** Never POST to ports 8000 or 8001.

```bash
uv run python - <<'EOF'
import collections, json, urllib.request
get = lambda url: json.load(urllib.request.urlopen(url, timeout=5))
edge = get("http://127.0.0.1:8001/api/sync")
print("mode:", edge["mode"], "| link:", edge["link"]["state"], "| queue:", len(edge["queue"]),
      "| summary-only:", edge["summary_only"])
print("arrivals by class:", dict(collections.Counter(a["class"] for a in edge["arrivals"])))
print("every arrival hash_ok:", all(a["hash_ok"] for a in edge["arrivals"]))
print("last cycle:", edge["last_cycle"])
print("hub counters:", get("http://127.0.0.1:8000/api/sync")["requests"])
events = get("http://127.0.0.1:8001/api/events")
print("edge verification:", dict(collections.Counter(e["verification"] for e in events)))
EOF
```

On a settled demo the queue is empty and `last_cycle` shows
`manifest_changed: False` and `fetched: 0`. Each cycle then costs one small ops
exchange (look at its `bytes`) and one "unchanged" manifest reply. The hub's
`manifest` and `ops` counters are equal or nearly so, one of each per edge
cycle, and
`fetch` is far smaller: records are fetched once. The arrivals mix
`P1_URGENT`, `P2_ROUTINE` (CDMs and element sets) and `P4_BULK` history.
Every active event reads `VERIFIED`.

**2. The order and the back-off, in process.**

```bash
uv run python - <<'EOF'
import datetime as dt
from sentinel.sync.agent import RetryBackoff
from sentinel.triage import Consequence as Q, PriorityClass as P, TriageKey, order
now = dt.datetime(2026, 9, 24, 12, tzinfo=dt.UTC)
h = lambda n: now + dt.timedelta(hours=n)
keys = [TriageKey("routine-soon", P.P2_ROUTINE, h(1), Q.ROUTINE),
        TriageKey("history", P.P4_BULK, h(0), Q.CRITICAL),
        TriageKey("urgent-later", P.P1_URGENT, h(30), Q.CRITICAL),
        TriageKey("urgent-sooner", P.P1_URGENT, h(10), Q.SERIOUS),
        TriageKey("omm:25544", P.P2_ROUTINE, h(50), Q.ROUTINE)]
for k in order(keys):
    print(f"{k.klass.name:<11} {k.deadline:%d %H:%MZ}  {k.consequence.name:<8} {k.item_id}")
backoff = RetryBackoff()
print("pulls sat out after each failure:", [backoff.failed("00ff00ff00ff00ff", n) for n in range(8)])
EOF
```

The two urgent items come first, sooner deadline first, although the other
is CRITICAL. `routine-soon` is due before both, and still waits for them. The
CRITICAL history record is last. The back-off reads `[1, 2, 4, 8, 16, 32, 32, 32]`.

**3. Watch an edge catch up over a LIMITED link.** This starts a private hub
and edge on free ports (it needs `make tools`). The link starts DENIED, the
hub receives the exercise backlog, and then the link opens at about 8 kbit/s.
It runs for 90 s.

```bash
uv run python - <<'EOF'
import collections, datetime as dt, time
from harness.cluster import Cluster, http
from harness.scenarios import post_cdm, scenario_cdms
released, _ = scenario_cdms(dt.datetime.now(dt.UTC))
with Cluster(hub_exercise=False, initial_link="DENIED", sync_interval_s=1.0) as c:
    for item in released:                  # the backlog waits at the hub
        post_cdm(c.hub, item.kvn)
    c.link("LIMITED")
    t0, seen, shown = time.monotonic(), 0, False
    while time.monotonic() - t0 < 90:
        sync = http("GET", f"{c.edge}/api/sync")
        if sync["queue"] and not shown:
            shown = True
            events = http("GET", f"{c.edge}/api/events")
            print(f"{time.monotonic() - t0:5.1f} s", dict(collections.Counter(e["verification"] for e in events)))
            for q in sync["queue"][:6]:
                print(f"        queue {q['class']:<11} {q['event_id'][:28]:<28} due {q['deadline'][:16]} {q['status']}")
        for a in sync["arrivals"][seen:]:
            print(f"{time.monotonic() - t0:5.1f} s arrived {a['class']:<11} {a['event_id'][:28]:<28} {a['verification']}")
        seen = len(sync["arrivals"])
        time.sleep(1)
EOF
```

What to look for:

- The first line shows every event as `HUB_ASSERTED` before any record has
  arrived: the summaries crossed first.
- The queue starts with `P1_URGENT` records in deadline order, the first one
  already `FETCHING`. Then come `P2_ROUTINE` CDMs and `omm:` element sets,
  interleaved by deadline, because both are routine.
- Each conjunction arrival reads `VERIFIED` as it lands. Element sets read
  `None`: they have no verification state.
- The routine event due soonest arrives after the urgent events due later.
  Class comes first.

For EDF against FIFO on the same link, with medians and ranges over repeated
runs, read the LIMITED section of `docs/ddil-results.md`. Chapter 9 explains
how that scenario keeps the comparison fair.

**4. The behaviour the numbers depend on, as tests.**

```bash
uv run pytest -v tests/sync/test_hostile_hub.py -k "admission or wait or denial or refused or filed"
uv run pytest -v tests/conjunction/test_verification.py
```

Read the test names as a specification: admission control counts the time
spent on the records ahead, the manifest wait grows and resets, a denial never
lengthens it, a refused record backs off, and a record is filed under the item
the manifest named. The verification tests cover every result field, the
UPDATING and LOCAL cases, and the log line a MISMATCH writes.

**5. The core stayed closed to the pass module.**

```bash
git diff --stat dd69b7e ac317e6 -- sentinel/sync sentinel/bus sentinel/crdt sentinel/triage
git diff --stat dd69b7e ac317e6 -- sentinel/passes | tail -1
```

The first prints nothing. Between those two commits the pass module, its
service and its API landed, and element sets started travelling through this
agent, with no change to the core. The second counts what changed in the pass
module over the same range.

## Design choices

**The edge pulls, over request/reply (ADR-008).** It buys an order chosen by
the node that knows its own link and deadlines, and a protocol that is state
based: a lost reply is just a retry next cycle. It costs a protocol of
Sentinel's own, which needs its own hostile-input tests
(`tests/sync/test_hostile_hub.py`). Rejected: a JetStream mirror, which
replicates in stream order, the FIFO baseline. See
[ADR-008](../system-design.md#adr-008--reference-data-application-level-priority-pull-not-transport-replication).

**Summaries first, and small (ADR-006).** It buys every event on the console
within seconds, even at about 8 kbit/s. It costs link time before any full
record, so each summary is held to `SUMMARY_MAX_BYTES`. See
[ADR-006](../system-design.md#adr-006--bandwidth-triage-by-decision-urgency).

**Class, then earliest deadline, then consequence (ADR-006).** It buys the
urgent record first, at almost no cost to when the whole backlog finishes.
Over one link the same bytes take the same time in any order.
`docs/ddil-results.md` has both measurements. It costs dependence on the
module's deadline and consequence, and the commit point is an operator
assumption (`mcp_lead_time_s`). Rejected: arrival order, which is what a
transport gives you.

**Admission control (ADR-006).** It buys a link spent on records that can
still arrive in time. It costs an event that may never get its latest CDM
while the link stays thin; the Sync panel marks it SUMMARY_ONLY. And it trusts
a measured rate that can lag the link (chapter 6).

**Check the bytes, keep the hub's identity, re-assess everything (ADR-008).**
It buys an edge that admits exactly the record the manifest announced, filed
under the event the hub assigned, and a VERIFIED that the edge checked rather
than echoed. It costs engine time at the edge, a back-off that delays a record
after a fault in transit, and a MISMATCH whenever the hub runs another engine
version or configuration, which is the point. Comparing the inputs hash alone
was rejected: it covers the inputs only, so a hub on another engine could
assert RED where the edge refuses and still pass
(`tests/conjunction/test_verification.py`).

**A protocol boundary the core never crosses (ADR-008).** `ReferenceRecords`,
`CompositeRecords` in the assembly layer and `.importlinter` buy mission
modules that plug in without touching `sentinel/sync`, proved for M3 by the
empty diff in Try it 5. Why keep it closed? The core holds the properties that
were hardest to get right: order, hash checks, back-off and budgets. Each is
held by hostile-input tests and strict mypy. A module that edited the core
would reopen all of them. So the core changes only deliberately: a bug fix
proven by a failing test, typing or documentation, or a design change with an
ADR (`CLAUDE.md`). The cost is that sync cannot learn module-specific needs. A reference-data class below routine CDMs, or batched fetch, would be a
deliberate core change, and it is open question 6 in `docs/system-design.md`.

**One record per round trip, and a hub offers only what edges use (ADR-008).**
It keeps the protocol simple and each reply checkable. It costs a round trip
per record, which is why a hub offers only the imaging catalog's element sets
by default. ADR-008's "Reference data on a thin link" records what offering
every set cost.

**FIFO mode stays in the code.** It buys the measured baseline: the same
transport and bytes, in arrival order with admission control off, so the EDF
advantage is a measurement rather than a claim. It costs a mode that must never
be deployed; `SENTINEL_SYNC_MODE` defaults to `edf`.

## How it fails

- **The link fails mid-cycle.** The exception ends the cycle. `run` counts a
  link failure and records `last_cycle: {error, at}`, and the next cycle
  starts again. Because operator data is state based and records are
  content-addressed, nothing half-done needs undoing. A record left
  `FETCHING` is simply asked for again.
- **The manifest reply is lost.** `Manifest request timed out` is logged, and
  the next wait doubles, up to 256 KiB worth, so a manifest that outgrew the
  wait still gets through a thin link. A denial never lengthens it, because
  the ops exchange runs first and fails first.
- **The manifest fails to apply.** The digest is remembered only after
  `apply_manifest` finishes, so the hub cannot answer "unchanged" to a manifest
  the edge never applied.
- **One summary is malformed.** Sync logs `Manifest entry skipped` with the
  item id and the error, and applies the rest. If sync can read the four
  fields but the conjunction module cannot display the summary, the module logs
  `Hub summary rejected` and does not store it. The records it names are still
  fetched and assessed locally, and the event then reads LOCAL.
- **The bytes are not the record asked for, or the module cannot ingest them.**
  Corrupted in transit, missing their `Sentinel-Sha256`, or a different genuine
  record: each is refused before ingest (`Sync record refused`, reason
  `hash_mismatch`). An `ingest` that raises logs `Sync record ingest failed`.
  Either way the record is re-queued and backed off, and the records behind it
  still come.
- **The module quarantines it.** Admission rejects it (a parse error, for
  example). It counts as an arrival with `status: rejected`, leaves the queue,
  and appears in the edge's `GET /api/quarantine`. `has` counts only admitted
  CDMs, so the record is wanted again, and fetched again, each time the hub's
  manifest changes. Checked with a hand-built hub: one fetch per manifest
  change, none in between.
- **The hub answers `not-found`.** The record goes back to `QUEUED` with no
  back-off and no log line, so it is asked for again on every pull. An honest
  hub says this only if a record vanished between manifest and fetch. A hub
  that keeps saying it costs the edge one round trip every cycle.
- **The deadline has passed.** In EDF mode a latest record whose deadline is
  behind the node clock is always held SUMMARY-ONLY once a rate is measured.
  For a conjunction the commit point has gone. For an element set it has
  gone stale, so an edge that first connects after a snapshot's sets go stale
  never fetches them, even over a fast link. The LIMITED and OPSEC scenarios run
  the node clock from the snapshot's day for this reason (`SNAPSHOT_CLOCK` in
  `harness/scenarios.py`). `make demo-local` runs on the real clock.
- **Same CDM, different result.** The event reads MISMATCH on the console, and
  the edge logs `Hub assertion not reproduced` with the fields that differ. It
  is never silently VERIFIED or silently replaced.
- **CDMs without a `CREATION_DATE`.** Each node orders an event's CDMs by its
  own receipt time. The edge fetches the latest first, so it can end up showing
  the hub's older record as its latest. That reads MISMATCH, never UPDATING,
  because nothing more is coming
  (`tests/conjunction/test_verification.py::test_an_edge_that_orders_the_hubs_records_otherwise_is_never_updating`).
- **A bug in the agent.** `Sync cycle failed` is logged with the traceback,
  the cycle counts as a link failure, and the agent keeps running.

## Check yourself

1. The edge sends the manifest digest back as `known` only after
   `apply_manifest` finishes. What would go wrong if it remembered the digest
   as soon as the reply arrived?

   <details><summary>Answer</summary>

   If storing the summaries or rebuilding the queue failed, the next request
   would carry a digest the edge never applied. The hub would answer
   "unchanged", and the edge would never build its queue. It would sit with no
   want-list until the hub's data happened to change.
   `tests/sync/test_hostile_hub.py::test_a_manifest_that_failed_to_apply_is_fetched_again`
   holds this.
   </details>

2. The hub lists records `[a1, a2, a3]` for event A, and the edge holds only
   `a1`. The event is RED, with its commit point in 20 hours. What is queued, in
   which class, and what does the edge console show for A right now?

   <details><summary>Answer</summary>

   `a2` as `P4_BULK` (history) and `a3` as `P1_URGENT` (the latest, CRITICAL,
   inside 72 h). `a3` is fetched first, `a2` last. The console shows the edge's
   own assessment of `a1`, labelled UPDATING, because the hub's latest record
   is not here yet.
   </details>

3. Admission control reads the node clock once per record, not once per pull.
   Give a case where reading it once would fetch a record that cannot arrive in
   time.

   <details><summary>Answer</summary>

   Two urgent records, due 80 s and 90 s from now, each needing 50 s at the
   measured rate. Read once, both look feasible. After the first arrives, only
   40 s remain for the second, which needs 50. Reading the clock again holds it
   SUMMARY-ONLY and saves the link. This is
   `test_admission_control_counts_the_time_spent_on_records_ahead`.
   </details>

4. An event reads VERIFIED. What exactly has been proved, and what has not?

   <details><summary>Answer</summary>

   Proved: the edge holds the CDM the hub listed as latest, byte for byte (the
   sha256 check). Its own engine assessed it and reached the hub's result on
   every field the summary carries, at the precision it carries them. Not
   proved: that the result is right. Two nodes running the same engine with the
   same bug would agree. Correctness comes from the engine's validation against
   NASA CARA (chapter 2), not from sync.
   </details>

5. Why does the edge file a fetched record under the manifest's item id, and
   refuse a reply whose `Sentinel-Event-Id` names a different item, rather than
   trust the header or regroup the CDM itself?

   <details><summary>Answer</summary>

   The manifest is what the edge asked about, and what the operator already
   sees as HUB_ASSERTED. Filing the record anywhere else would attach a
   different event's CDM to it. Regrouping at the edge would re-derive
   identity. Updates fetched out of order, urgent first, could then split one
   event into two. The hub assigns identity once and it travels with the
   record (ADR-008).
   </details>

6. A third mission module will offer 300 items. What must change in
   `sentinel/sync`, and what gets more expensive on a thin link?

   <details><summary>Answer</summary>

   Nothing in `sentinel/sync`. The module implements `ReferenceRecords`,
   registers an item-id prefix in `CompositeRecords` through `_sync_records`,
   and its summaries carry `e`, `dl`, `q` and `c`. What grows: 300 more
   summaries in every changed manifest, and one round trip per record. Those
   records also compete with CDMs of the same class, by deadline. ADR-008's
   thin-link section says to offer only what edges use.
   </details>

## Where next

- [Chapter 8, Operator data](08-operator-data.md): what `exchange_ops` carries, and why the budget never loses an entry.
- [Chapter 9, The DDIL harness](09-ddil-harness.md): the LIMITED scenario behind the EDF and FIFO numbers, and why each run starts with the link down.
- [Chapter 10, Passes and screening](10-passes-and-screening.md): the element sets this agent delivers, and what the edge computes from them.
- [Chapter 3](03-cdm-and-events.md) for the ingest and event grouping `ingest` runs at the edge, and [chapter 2](02-risk-engine.md) for the engine that makes VERIFIED worth something.
- Reference: `docs/icd/sync-envelope.md` (every field, class, header and state, held to the code by `tests/docs/test_sync_envelope.py`), `docs/system-design.md` (ADR-006 and ADR-008), `docs/ddil-results.md`, and "How to extend" (a) in `docs/technical-guide.md` for adding a module that syncs.
