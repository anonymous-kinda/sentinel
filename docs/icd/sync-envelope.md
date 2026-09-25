# Interface control: sync envelope

This is how an edge pulls reference data (CDMs, element sets) from a hub and
exchanges operator data with it (ADR-006, ADR-008). It is the one interface
with no published standard behind it. It borrows Bundle Protocol's
store-carry-forward semantics without implementing BPv7, and says so plainly
rather than overclaiming (`docs/system-design.md` §5).

The transport is NATS request/reply over the leafnode link, served by the
hub. Subjects, headers and payload schemas are in `docs/icd/asyncapi.yaml`.
Bodies are canonical CBOR (RFC 8949 §4.2), except a fetched record, which is
the record's own bytes.

The sync layer is mission-agnostic. It reads four generic summary fields and
never learns what a conjunction or an element set is. A mission module plugs
in through the `ReferenceRecords` protocol. `.importlinter` forbids
`sentinel.sync` from importing any mission module.

`tests/docs/test_sync_envelope.py` holds this document to `sentinel/sync`,
`sentinel/triage` and the modules' adapters. Every field, class, state,
header and protocol method below is read from the code and compared both
ways.

## One cycle

The edge's `SyncAgent` runs a cycle every 2 s by default
(`SENTINEL_SYNC_INTERVAL_S`):

1. **Operator data (P0).** `ops.<hub_id>.exchange` sends this node's CRDT
   contexts and what the hub was last known to lack. The reply carries what
   this node lacks. Each way is held to a budget, what the measured link
   moves in 10 s (at most 256000 bytes): the oldest part that fits, always
   at least one item. A backlog after a long denial drains over several
   cycles, and the manifest and records still get the link in each. It is
   state-based, so a lost reply only means the next cycle sends a little
   more, and an item's dots enter the peer's context only when that item
   is merged, so the part not yet sent is never lost.
2. **Manifest (P0).** `sync.<hub_id>.manifest` fetches one summary per active
   item. It is skipped when the hub's digest is unchanged. Every event is then
   visible on the edge as `HUB_ASSERTED`, before any record arrives.
3. **Records.** The want-list is a set difference: the hub's records minus
   this node's (`has`). It is ordered by triage key and fetched one at a time
   on `sync.<hub_id>.fetch`, within a budget of max(5 × interval, 10 s) per
   cycle.
4. **Re-admission.** Each record goes through its module's own admission
   (`ingest`). A conjunction CDM is re-assessed on the edge and compared with
   what the hub asserted.

A record the edge refuses (see `Sentinel-Sha256` below), or one whose
`ingest` raises, does not stop the pull. It is logged (`Sync record refused`
or `Sync record ingest failed`), re-queued, and sits out 1 pull, then 2, 4
and so on up to 32, so it never costs a thin link a round trip every cycle.
The records behind it are fetched. It is not a link failure.

A request's timeout is 6 s + 1.5 × expected bytes ÷ max(measured rate,
400 B/s). Before any rate is measured, 1000 B/s is assumed. A timeout or "no
responders" is expected over a DDIL link: it counts as a link failure, and
the next cycle tries again.

A record's expected bytes are its size in the manifest. An operator-data
exchange's are the request, the budget and 2000 bytes for the hub's
contexts. It does not grow after a timeout, so a denial never lengthens
the wait. A manifest's are
the size of the last manifest received, at least 4000, doubled for each
manifest timeout in a row up to 256 KiB. A manifest that outgrew the wait
still reaches the edge over a thin link, and the first one that arrives
brings the wait back to its own size.

## Summary

A manifest is a CBOR array of summaries, one per item, concatenated across
the hub's modules. The conjunction module lists its own active events (TCA
in the future) and does not re-serve summaries it holds from another node.
The pass module lists the element sets the hub offers (below).

### Fields sync reads

| Field | Type | Meaning |
|---|---|---|
| `e` | string | Item id: a conjunction event id, or a prefixed id such as `omm:40115`. |
| `dl` | integer | Deadline, Unix epoch seconds (UTC). For a conjunction, the maneuver commit point; for an element set, the moment it goes stale. |
| `q` | integer 0-3 | Consequence (below). |
| `c` | array | The item's records, oldest first, each `[sha16, bytes, created_epoch]`. `sha16` is the first 16 hex characters of the record's sha256. The last entry is the latest record. |

Sync reads nothing else. Whatever else a module puts in a summary travels
with it, is stored as the hub's assertion (`put_summaries`), and is the
module's business.

A summary whose four fields sync cannot read as above (a non-empty string
id, an epoch deadline, a consequence 0-3, records of 16 lowercase hex
digits, bytes ≥ 0 and a created epoch) queues nothing. It is logged as
`Manifest entry skipped`, and the rest of the manifest is applied.

### Conjunction summary

What the conjunction module adds, so an edge can show every event before
any CDM arrives:

| Field | Meaning |
|---|---|
| `p` | Primary: `[designator, name]`, the name cut to 24 characters. |
| `s` | Secondary: `[designator, name]`. |
| `t` | TCA, Unix epoch seconds. |
| `b` | Band: `R`, `A`, `G` or `U` (unassessed). |
| `w` | Worst-case band from max Pc, only when diluted; otherwise null. |
| `pc` | log10 Pc to 3 decimals; null when refused; -999 for a Pc of 0. |
| `px` | log10 max Pc, same encoding. |
| `d` | Dilution flag. |
| `r` | Refusal reason, or null. With a reason, `pc` is null: no Pc travels without its method. |
| `md` | Miss distance, m, to 0.1. |
| `rs` | Relative speed, m/s, to 0.1. |
| `h` | First 16 hex characters of the hub's assessment inputs hash. Verification compares against it. |
| `dc` | Data class: `R` (REAL), `D` (DERIVED) or `X` (EXERCISE). |

At the bottom of the degradation ladder a summary renders as one line that
can be read over a voice net:

```
EXSAT-1 X EX-DEB 118 TCA 242017Z MCP 241217Z RED PC 6.3E-3 DIL WC 6.9E-3
```

An element-set summary carries only the four generic fields.

### Size limit

One summary without its `c` list is at most 256 bytes of CBOR. This is
asserted for every exercise event in `tests/sync/test_hub_edge.py`
(`SUMMARY_MAX_BYTES`). At about 8 kbit/s, every event is visible within a
few seconds.

## Priority classes

| Class | Value | Holds |
|---|---|---|
| `P0_SUMMARY` | 0 | Summaries and operator deltas. Always first by construction: the operator-data exchange and the manifest run before any record is fetched. |
| `P1_URGENT` | 1 | The latest record of an item whose consequence is `SERIOUS` or worse and whose deadline falls within the urgent window (72 h by default, `ConjunctionPolicy.urgent_window_s`). |
| `P2_ROUTINE` | 2 | Every other latest record. Element sets land here. |
| `P3_REFERENCE` | 3 | Catalog refresh. Defined; the agent assigns nothing to it today. |
| `P4_BULK` | 4 | Superseded records (history). Last. |

## Order

Class first, then **earliest deadline first** within a class, then higher
consequence first as the tie-breaker, then item id. An item with no deadline
sorts last in its class. EDF is optimal on a single resource when a feasible
schedule exists (Liu & Layland, 1973). The key is `TriageKey.sort_key` in
`sentinel/triage`.

Mode `fifo` exists only as the measured baseline for the LIMITED scenario.
It orders by record creation time and turns admission control off.

## Consequence

| Level | Value | For a conjunction |
|---|---|---|
| `ROUTINE` | 0 | GREEN, with no worst case above GREEN. Element sets are always ROUTINE. |
| `WATCH` | 1 | UNASSESSED (refused), or worst case AMBER. |
| `SERIOUS` | 2 | AMBER, or worst case RED. |
| `CRITICAL` | 3 | RED. |

## Admission control and queue states

In EDF mode, when the link rate has been measured, the latest record of an
item that cannot arrive before its deadline at that rate is not fetched: the
item is held `SUMMARY_ONLY`, and the console shows the hub's summary. The
link is spent on records that can still arrive in time. The node clock is
read as each record comes up, so the time spent fetching the records ahead
of it in the same pull counts against its deadline.

### Queue states

| State | Meaning |
|---|---|
| `QUEUED` | Waiting, or put back after the hub answered with `Sentinel-Error` or with a reply the edge refused (Headers, below). |
| `FETCHING` | Request in flight. |
| `ARRIVED` | Fetched and admitted; dropped from the queue at the end of the pull. |
| `SUMMARY_ONLY` | Admission control: it cannot arrive before its deadline at the measured rate. |

`GET /api/sync` on an edge shows the queue, recent arrivals and the items
held summary-only.

## Plugging in a mission module

### ReferenceRecords

`sentinel/sync/records.py`. The sync layer depends on this protocol only.

| Method | Contract |
|---|---|
| `manifest()` | Summaries of this node's items: the four generic fields, plus anything the module needs. |
| `get(sha16)` | The record's raw bytes and its headers (below), or `None`. |
| `has(sha16)` | Whether this node already holds the record, so it is not fetched again. |
| `put_summaries(summaries, origin)` | Store the hub's summaries as its assertion. |
| `ingest(raw, source, data_class, item_id)` | Admit a fetched record through the module's own admission policy. Returns `status`, `sha256` and `verification`. |

### Item-id prefixes

A node runs one `SyncAgent` or `SyncServer` over one `ReferenceRecords`. With
more than one module, the node's assembly layer composes them with
`CompositeRecords` (`sentinel/api/records.py`), so `sentinel/sync` never
changes when a module is added. The composite concatenates manifests, asks
every module for `get` and `has`, and routes `put_summaries` and `ingest` by
the item id's prefix. An id with no registered prefix goes to the default
module, the conjunction module.

| Prefix | Module | Item id | Deadline | Consequence | Data class |
|---|---|---|---|---|---|
| `omm:` | Pass module: public element sets (`sentinel/passes/sync_adapter.py`) | `omm:<NORAD id>` | Element epoch + 3 days: when it goes stale | `ROUTINE` | `REAL` |

An element-set record is the set's canonical OMM JSON bytes. An edge loads no
snapshot of its own unless configured to (`SENTINEL_ELEMENTS`). It receives
its element sets from the hub this way, and each one it accepts makes its
pass module publish `node.<node_id>.passes.updated` once the burst settles.
That event is node-local and carries no unit and no coordinates.

### Element sets offered

Every record costs a round trip on a thin link, so a hub offers only what
edges use. `SENTINEL_SYNC_ELEMENTS` sets the scope:

| Scope | The hub's manifest lists |
|---|---|
| `catalog` | The default. Only the element sets of the imagers in the pass module's catalog. |
| `all` | Every element set the hub holds. |

A unit's position and its pass windows are not records. They never enter a
manifest and never leave the node (ADR-010).

## Messages

| Subject | Request (CBOR) | Reply |
|---|---|---|
| `ops.<hub_id>.exchange` | `from`, `log_ctx`, `mv_ctx`, `push` (`log` entries and `reg` registers the hub lacks, within the budget), `budget` (bytes the edge will take in the reply) | CBOR `pull` (what the edge lacks, within the budget; everything if `budget` is missing or not a positive integer), `ctx` (the hub's contexts), `merged` (counts) |
| `sync.<hub_id>.manifest` | `from`, `known` (the last digest, or null) | CBOR array of summaries; or an empty body with `Sentinel-Unchanged` when `known` is current |
| `sync.<hub_id>.fetch` | `sha` (sha16), `from` | The record's bytes, exactly as the hub received them |

### Headers

| Header | On | Value |
|---|---|---|
| `Sentinel-Digest` | manifest reply | sha256 of the manifest's canonical CBOR. The edge sends it back as `known` once it has applied that manifest, so a manifest that failed to apply is fetched again. |
| `Sentinel-Unchanged` | manifest reply | `1` when `known` matched: the body is empty. |
| `Sentinel-Schema` | manifest reply with a body | `sentinel.manifest/1`. |
| `Sentinel-Event-Id` | fetch reply | The item id the hub assigned. The edge files the record under the item id the manifest named for it, which is the same hub-assigned id, and never re-derives one; otherwise updates fetched out of order would split one event into two. If this header is sent, it must equal that id, or the reply is refused. |
| `Sentinel-Data-Class` | fetch reply | `REAL`, `DERIVED` or `EXERCISE`. A generator's ORIGINATOR mark still wins on admission (`docs/icd/cdm-profile.md`). |
| `Sentinel-Sha256` | fetch reply | The full sha256 of the record bytes. The edge hashes what it received and admits the record only if that hash begins with the `sha16` it asked for and equals this header. A missing header is not a match. Anything else is refused before ingest: logged as `Sync record refused` with `hash_ok` false, and re-queued. Every arrival therefore carries `hash_ok` true. |
| `Nats-Msg-Id` | fetch reply | The same sha256, as a NATS message id. The agent does not read it. |
| `Sentinel-Kind` | fetch and ops replies; node-local events | `record.full` on a fetch reply, `ops.exchange` on an ops reply. |
| `Sentinel-Error` | any reply | `not-found` when the hub holds no record with that prefix (the item is re-queued). `responder-failed` when the hub's responder raised (NATS transport). |

## Verification states

Per conjunction event, on the edge. `GET /api/events` carries it as
`verification`.

| State | Meaning |
|---|---|
| `LOCAL` | This node's own data. There is no hub summary for the event. |
| `HUB_ASSERTED` | Known only from the hub's summary. No CDM is here yet; the assessment shown is the hub's, marked as such, and could not have been recomputed because no covariance travelled. |
| `UPDATING` | The hub has a newer CDM for the event than the latest one here, not yet fetched. |
| `VERIFIED` | The CDM was fetched and re-assessed here, and its inputs hash matches the hub's `h`. |
| `MISMATCH` | Same CDM, different result. Flagged, never hidden. |

Element sets have no verification state (`null`). They are checked by hash
and by the element store's own admission.
