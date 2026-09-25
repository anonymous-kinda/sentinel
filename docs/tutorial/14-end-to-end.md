# 14. End to end: one CDM through the whole system

One conjunction message from a file on disk to a verified event on an edge, a decision made offline, and the merge.

## What you will learn

- The whole path of one CDM, `EX-DIL-03`, through eight stops: file, codec, engine, store, manifest, edge, operator data, console.
- The code at each stop, named by file and symbol, and the one thing at each stop that is easy to get wrong.
- The identities that carry the CDM across the system: its sha256, its event id, its inputs hash, and a decision's dot.
- How to watch every stop happen on your own hub and edge, with a command or an HTTP call.
- How the stops fail, and where each failure shows.

## Why it exists

Chapters 2 to 13 each took one part apart. An operator never sees parts. They see an event appear, turn VERIFIED, change band, and carry a decision marked REVIEW REQUIRED. This chapter joins the parts to that experience, so you can answer the question an operator or a reviewer will actually ask: "why does the screen say that?"

It also proves that the guarantees hold *together*, not just one at a time:

- every number on the edge's screen was computed on the edge from the original bytes, and those bytes are the ones the hub announced;
- a thin link carries the summary first and the urgent record next;
- a decision made with the link down is kept, signed, merged and, when its CDM is superseded, flagged rather than silently trusted.

The same path is the one you walk backwards when something looks wrong. Knowing each stop's code and each stop's evidence is how you debug Sentinel.

## Concepts

### The route

```
 stop 1  EX-DIL-03-….cdm           a KVN file on disk
            │  POST /api/ingest/cdm (on the hub)
 stop 2  parse → validate → Conversion                        sentinel/cdm
 stop 3  assess → band, worst case, MCP                       sentinel/risk, conjunction/policy.py
 stop 4  store raw bytes + assessment; publish node.hub.cdm.accepted.<event>
 stop 5  compact summary in the hub's manifest                conjunction/summaries.py
 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ leaf link (Toxiproxy in the harness) ─ ─ ─ ─ ─ ─ ─ ─
 stop 6  edge: manifest → HUB-ASSERTED → want list → fetch by sha16
         → hash checks → ingest → re-assess → compare → VERIFIED    sentinel/sync
 stop 7  decision and triage status written on the edge while DENIED;
         merged both ways on reconnect; REVIEW REQUIRED        sentinel/ops, sentinel/crdt
 stop 8  /api/stream → console refetches → chips, Pc, conflict   web/
```

Stops 2 to 4 run twice: once on the hub when the file is posted, and again on the edge when the fetched bytes arrive. That repetition is the design, not an accident (stop 6).

### The CDM we follow

The exercise scenario's `EX-DIL` event (`SCENARIO` in `sentinel/conjunction/exercise.py`) is EXSAT-1 against a fictional debris object, EX-DEB 412. It has five updates. The miss distance never changes; only the debris object's covariance grows, as its tracking degrades:

| Update | Created, relative to the scenario start | What the engine concludes |
|---|---|---|
| EX-DIL-01 | 20 h before | GREEN |
| EX-DIL-02 | 12 h before | AMBER |
| **EX-DIL-03** | **4 h before** | **RED, not diluted** |
| EX-DIL-04 | 72 s after | RED, and now *diluted*: the Pc fell because the uncertainty grew |
| EX-DIL-05 | 216 s after | AMBER, diluted, worst case RED |

EX-DIL-03 is the latest update when the scenario starts. We follow it to the edge, make a decision against it with the link down, and let EX-DIL-04 supersede it. The later updates are the dilution trap in miniature: the Pc falls while the risk does not.

### The identities that travel

| Identity | What it names | Made by | Where you see it |
|---|---|---|---|
| sha256 | the exact bytes of one CDM | `ConjunctionService.ingest` | the ingest reply; `latest_cdm_sha256`; `sha256sum` of the file |
| sha16 | the same, first 16 hex digits | `ConjunctionService._offered_events` | the manifest's `c` list; `sha` in `GET /api/sync` |
| event id | one conjunction across its updates: `<primary>-<secondary>-<TCA to the second>` | the node that first ingests it, `_new_event_id` | `event_id` everywhere; the `Sentinel-Event-Id` header |
| inputs hash | what the engine computed from: both states, covariances and radii | `Conjunction.inputs_hash` in `sentinel/risk/types.py` | `assessment.inputs_hash`; `h` in the summary |
| engine version | Sentinel's version plus a hash of `AssessmentConfig` | `ConjunctionService.__init__` | `engine_version` in `GET /api/node` |
| dot | one operator write: `(node, sequence)` | `SignedLog.append`, `MVMap.write` | `dot` in `GET /api/events/{id}/ops` |

Keep the sha256, the event id and the inputs hash apart. Two different files can share an inputs hash (a changed comment changes the sha256, not the inputs). Two different events can share a pair of objects. Verification checks both the record and the inputs for exactly that reason.

### What crosses the link

Only three request/reply subjects, all served by the hub: `sync.hub.manifest`, `sync.hub.fetch` and `ops.hub.exchange`. The summary carries the hub's *assertion* about its result. The fetch carries the original bytes. Nothing else about the conjunction crosses: not the hub's assessment as a fact, and not its console events (`node.hub.>`), which the edge's leaf configuration refuses.

### Verification states

```
 HUB_ASSERTED  the hub's summary is here; none of the event's CDMs is
 UPDATING      some CDMs are here, but not the one the hub lists as latest
 VERIFIED      the hub's latest is here, and this node's result equals the hub's assertion
 MISMATCH      the hub's latest is here, and at least one asserted field differs
 LOCAL         no hub summary for the event, or this node holds a CDM newer than any the hub listed

 on the edge, for our event:
   HUB_ASSERTED ──► VERIFIED ──(a manifest lists EX-DIL-04)──► UPDATING ──(it arrives)──► VERIFIED
```

`_verification` in `sentinel/conjunction/service.py` decides it on every read. VERIFIED is always about the hub's *latest* record, compared at the precision the summary carries. On a fast link UPDATING lasts only between applying a manifest and fetching the record it names; on a thin link you can watch it.

## Code walkthrough

### Stop 1. A CDM on disk

**Code.** `generate` and `build_message` in `sentinel/conjunction/exercise.py`; `_exercise_generate` in `sentinel/cli_ext.py`; `emit` in `sentinel/cdm/kvn.py`.

`generate(epoch)` turns every `EventScript` into dated CDMs. `build_message` places both objects on circular orbits, puts the requested miss in the encounter plane, writes each covariance from three standard deviations with a radial/along-track correlation, and marks the message at the source: `ORIGINATOR = SENTINEL-EXERCISE`, an EXERCISE comment, fictional designators in the 99xxx range, and `COMMENT HBR = 20 [m]`, the combined hard-body radius in NASA CARA's convention.

*Easy to get wrong:* updates dated after the epoch carry a `CREATION_DATE` in the future. A node's exercise feeder holds them until its clock gets there. Posted by hand they are accepted at once, and a node orders an event's CDMs by `CREATION_DATE`, not by arrival. The file name is not an identity either: the bytes' sha256 is.

### Stop 2. Parsed and validated

**Code.** `parse_bytes` in `sentinel/cdm/kvn.py`; `validate`, `CdmRejected` and `CdmWarning` in `sentinel/cdm/validate.py`; `to_conjunction` and `resolve_radii` in `sentinel/cdm/to_conjunction.py`.

`parse_bytes` reads structure only: keys, values, unit labels and comments, in two object blocks. `validate` applies the admission rule. Input that would make the answer *wrong* raises `CdmRejected` with a stable code; input that makes it *incomplete* returns a `CdmWarning`. `to_conjunction` then builds the engine's input, a `Conjunction` of two `ObjectState`s in km, km/s and m², and takes the hard-body radius from the COMMENT line, split evenly between the objects.

*Easy to get wrong:* a missing covariance is incomplete, not wrong. The message is admitted and the engine refuses its Pc. Only input that would corrupt a number, such as a position labelled in metres, is quarantined.

### Stop 3. Assessed and banded

**Code.** `assess` in `sentinel/risk/engine.py`; `triage` and `ConjunctionPolicy` in `sentinel/conjunction/policy.py`.

`assess` runs its gates in order (covariance present, radius known, covariances valid, relative speed high enough, TCA consistent, projected covariance usable, uncertainty flat enough), integrates the Pc, then searches the covariance scale `k` for the worst case, `pc_max` at `k*`. `k* < 1` means the Pc would rise if the data were better: the result is diluted. [Chapter 2](02-risk-engine.md) has the maths.

`triage` turns that into what the operator acts on: the band from the Pc (only when the method is `FOSTER_ESTES_2D`), the worst-case band from `pc_max` (only when diluted), a consequence from both, and the maneuver commit point, TCA minus 8 hours.

*Easy to get wrong:* triage is not stored. `ConjunctionService.event_summary` computes it on every read. Change the policy and every view changes at once; change the engine configuration and the engine version changes, so every assessment is recomputed from the raw bytes rather than trusted from the cache.

### Stop 4. Stored and published

**Code.** `ConjunctionService.ingest`, `_event_for`, `_new_event_id`, `_assess_sha` and `event_summary` in `sentinel/conjunction/service.py`; `ConjunctionStore` in `sentinel/conjunction/store.py`; `cdm_accepted` in `sentinel/bus/subjects.py`; the `/api/stream` route in `sentinel/api/app.py`.

`ingest` hashes the bytes first; a hash it already holds is a no-op. Then it parses and converts (stop 2). The data class comes from the originator's mark if there is one, so an exercise message stays EXERCISE whatever route it came by. `_event_for` groups it: same pair of objects, same data class, TCA within 60 s. The first update creates the event id, and the next two join it. The raw bytes go into SQLite as the source of truth, the assessment is cached per sha256 and engine version, and the event summary is published on `node.hub.cdm.accepted.<event id>` with the header `Sentinel-Kind: cdm.accepted`.

*Easy to get wrong:* that publish is node-local. It reaches the hub's own console through `/api/stream` and never reaches the edge (ADR-009). The edge learns about this CDM only by asking for it.

### Stop 5. Summarised into the hub's manifest

**Code.** `ConjunctionService.manifest` and `_offered_events`; `compact_summary` in `sentinel/conjunction/summaries.py`; `ConjunctionRecords.manifest` and `get` in `sentinel/conjunction/sync_adapter.py`; `CompositeRecords` in `sentinel/api/records.py`; `SyncServer._manifest` and `_fetch` in `sentinel/sync/server.py`.

For every active event whose data is the hub's own, `compact_summary` writes a small map:

| Key | Meaning | Key | Meaning |
|---|---|---|---|
| `e` | event id | `h` | inputs hash, 16 hex digits |
| `p`, `s` | primary and secondary: id and name | `dc` | data class, one letter |
| `t` | TCA, epoch seconds | `r` | refusal reason, or null |
| `b`, `w` | band and worst-case band, one letter | `md`, `rs` | miss distance and relative speed, to 0.1 |
| `pc`, `px` | log10 of Pc and max Pc, to 3 decimals | `dl` | deadline: the MCP, epoch seconds |
| `d` | diluted | `q` | consequence, 0 to 3 |
| `c` | every CDM of the event: `[sha16, bytes, created]`, oldest first | | |

`SyncServer._manifest` encodes the whole list, conjunction summaries and element-set summaries together, as CBOR, with a digest. An edge that already holds that digest gets an empty reply marked `Sentinel-Unchanged`. `SyncServer._fetch` returns a record's original bytes, untouched, with `Sentinel-Sha256`, `Sentinel-Event-Id` and `Sentinel-Data-Class` headers.

*Easy to get wrong:* sync reads four of those keys, `e`, `dl`, `q` and `c`. Everything else is the conjunction module's assertion, which only the conjunction module on the edge will read and check. And a node offers only events it computed itself (`verification` `LOCAL`), so an edge never re-offers what it pulled from its hub.

### Stop 6. Pulled, fetched, checked, re-assessed, VERIFIED

**Code.** `SyncAgent.cycle`, `fetch_manifest`, `apply_manifest`, `_rebuild_queue`, `_wanted`, `pull` and `_fetch` in `sentinel/sync/agent.py`, with `read_summary` and `_is_the_record_asked_for`; `ConjunctionRecords.put_summaries` and `ingest`; `summary_problem`, `expand_summary` and `disagreements` in `sentinel/conjunction/summaries.py`; `ConjunctionService._verification`.

One edge cycle runs operator data first (stop 7), then the manifest, then records:

1. **Summaries.** `apply_manifest` hands the summaries to `put_summaries`, which stores each one it can display. From this moment the edge lists the event as `HUB_ASSERTED`, built by `expand_summary` from the hub's numbers and marked as the hub's.
2. **Want list.** `_wanted` lists every record the edge lacks. The latest record of an event with consequence SERIOUS or higher, due within the 72-hour urgent window, is `P1_URGENT`; any other latest record is `P2_ROUTINE`; older records are `P4_BULK`. `order` from `sentinel/triage/__init__.py` sorts by class, then deadline, then consequence. EX-DIL-03 is RED (consequence CRITICAL) and its commit point is under a day away, so it is P1 and fetched first; EX-DIL-01 and -02 follow as history.
3. **Admission control.** In `pull`, a latest record the measured link cannot deliver before its deadline is marked `SUMMARY_ONLY` instead of fetched.
4. **Fetch and check.** `_fetch` asks for the sha16. It admits the reply only if the bytes' sha256 starts with that sha16 *and* equals the `Sentinel-Sha256` header, and only if `Sentinel-Event-Id` names the same event.
5. **Re-assess.** `ConjunctionRecords.ingest` calls the same `ConjunctionService.ingest` as stop 4, with source `sync:hub` and the hub's event id. Stops 2 to 4 run again, on the edge, from the bytes.
6. **Compare.** `_verification` finds the hub's latest record present, and `disagreements` re-encodes the edge's own result exactly as the hub encoded its own, field by field: `h`, `r`, `b`, `w`, `pc`, `px`, `d`, `md`, `rs`. No difference: VERIFIED. Any difference: MISMATCH, and the edge logs `Hub assertion not reproduced` with the fields.

*Easy to get wrong:* the priority class is chosen by sync from `dl` and `q`, not by the conjunction module. (`triage_key` in `sentinel/conjunction/policy.py` looks as if it does that, but nothing calls it.) And VERIFIED means "my result for the hub's latest record equals what the hub asserted". It does not mean "current": with the link down, it describes the last manifest that arrived.

### Stop 7. A decision made offline, merged on reconnect

**Code.** The `decision` and `annotation` routes in `sentinel/api/app.py`; `OpsService.append`, `annotate`, `payload_for`, `merge_payload` and `_entry_view` in `sentinel/ops/service.py`; `SignedLog` in `sentinel/crdt/log.py`; `MVMap` in `sentinel/crdt/mvmap.py`; `SyncAgent.exchange_ops` and `SyncServer._ops`; `ConjunctionService.current_ref`; `LinkMonitor` in `sentinel/linkstate/monitor.py`.

With the link black-holed, every exchange fails. `LinkMonitor.state` turns DENIED once 8 s pass with no success and a failure since; until then it reports DEGRADED, or the LIMITED reading it already had. Nothing local depends on the link, so the console keeps answering.

The operator records a decision. `OpsService.append` binds it to `current_ref`, the CDM the edge shows *now*: EX-DIL-03's full sha256, its inputs hash and message id. `SignedLog.append` gives it the dot `(edge-alpha, 1)`, chains it to the node's previous entry and signs it with the node's Ed25519 key. The operator also sets the triage status; `MVMap.write` stores it in a register with its own dot. Meanwhile the hub's operator sets a different status on the same event, and EX-DIL-04 arrives at the hub.

On reconnect, the first exchange carries each side's causal contexts, what the peer lacks within a byte budget, and nothing more. The signed log merges by union, so both nodes hold the decision. The two status writes were concurrent (neither saw the other), so the register keeps both: a CONFLICT. Then the manifest brings EX-DIL-04, the edge fetches and verifies it, and `_entry_view` compares the decision's `cdm_sha256` with the new `current_ref`. They differ: `review_required` is true.

*Easy to get wrong:* REVIEW REQUIRED is not stored or synced. Each node computes it when it reads, from its own current CDM. The hub flags the decision as soon as the entry merges, because it already holds EX-DIL-04; the edge flags it once EX-DIL-04 has arrived there. Resolving the conflict is an ordinary write over both values, and it appends a signed `RESOLUTION` entry naming what it superseded.

### Stop 8. Shown in the console

**Code.** `useStream` and `useResource` in `web/src/api/client.ts`; `App` in `web/src/App.tsx`; `EventList` and `BandChip` in `web/src/components/EventList.tsx`; `VerificationChip` in `web/src/components/Verification.tsx`; `PcValue`, `EventDetail`, `OpsPanel`, `SyncPanel` and `LinkControl` in `web/src/components/`.

The console opens `/api/stream`, which forwards the node's `node.<id>.>` events as server-sent events named by `Sentinel-Kind`. Every event bumps a version counter, and every `useResource` on screen refetches. The stream is a doorbell: the screen always shows what the API says now, not what a message said.

For our event the edge shows, in order:
- a `HUB-ASSERTED` chip and the callout "Asserted by hub, not computed here", with the summary's one-line voice form;
- then `✓ VERIFIED`, the RED band, and the CDM count climbing as history arrives;
- after reconnect, EX-DIL-04: still RED, now with a DILUTED chip and the Pc drawn with its worst case (only `PcValue` may draw a Pc); the triage status as a CONFLICT naming both operators and nodes; and the MANEUVER decision with `REVIEW REQUIRED`, `✓ signed` and "against EX-DIL-03-…";
- after EX-DIL-05, the AMBER band beside `worst RED`.

The top bar's `LINK` chip is the measured state, never the preset.

*Easy to get wrong:* REVIEW REQUIRED appears without any `ops.changed` event. The `cdm.accepted` for EX-DIL-04 bumps the version, `OpsPanel` refetches `/api/events/{id}/ops`, and the node recomputes the flag.

## Try it

You need two terminals, the pinned binaries and the built console. `make web` needs the console's npm dependencies, which `make install` fetches once.

```bash
export PATH=$HOME/.local/bin:$PATH
make tools web
```

**Your own hub and edge.** `make demo-local` starts the exercise feeder on its hub, which would release its own copy of EX-DIL. For this walk you post every CDM yourself, so start a pair with the feeder off, on ports 8140 and 8141. In terminal 1:

```bash
uv run python - <<'EOF'
import time
from harness.cluster import Cluster

with Cluster(hub_exercise=False, web=True, hub_port=8140, edge_port=8141) as c:
    print(f"export HUB={c.hub} EDGE={c.edge} HUB_NATS=nats://127.0.0.1:{c.ports['hub_client']}", flush=True)
    print(f"# logs and state: {c.dir}", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
EOF
```

It prints an `export` line once both nodes answer. Paste that line into terminal 2; every command below runs there. The hub also loads NASA's reference library, but those events are in the past, so they stay out of the manifest and off the edge.

**Stop 1. The file.**

```bash
CDMS=$(mktemp -d)
uv run sentinel exercise generate --out $CDMS
ls $CDMS | grep DIL
CDM=$(ls $CDMS/EX-DIL-03-*.cdm)
grep -E '^(CREATION_DATE|ORIGINATOR|MESSAGE_ID|TCA|MISS_DISTANCE|COMMENT) ' $CDM
```

Five EX-DIL files, named by message id. In EX-DIL-03, look for the originator's mark, the TCA 30 hours out, and `COMMENT HBR = 20 [m]`.

**Stops 2 and 3. Codec and engine, no node.**

```bash
uv run sentinel cdm parse $CDM
uv run sentinel assess $CDM
uv run sentinel assess $CDMS/EX-DIL-04-*.cdm
```

`cdm parse` shows no warnings and a 20 m radius from the comment. `assess` gives EX-DIL-03 a Pc by `FOSTER_ESTES_2D` with no `DILUTED` line (`k*` above 1). EX-DIL-04 has the same miss distance, a lower Pc and a `DILUTED` line (`k*` below 1). Note the two `inputs` hashes: different inputs, different hashes.

**Stop 4. Into the hub.** Make the link thin first, so you can watch the edge's side in slow motion:

```bash
curl -s -X POST -H 'Content-Type: application/json' -d '{"preset": "LIMITED"}' $EDGE/api/demo/link; echo
for f in $CDMS/EX-DIL-0[123]-*.cdm; do curl -s --data-binary @$f $HUB/api/ingest/cdm; echo; done
sha256sum $CDM
curl -s $HUB/api/events | python3 -m json.tool | grep -E '"(event_id|band|cdm_count|latest_message_id|verification)"'
```

Each reply is `"status":"accepted"` with the same `event_id`: one event, three updates. The third reply's `sha256` is exactly what `sha256sum` prints for the file. On the hub the event is RED, its latest message is EX-DIL-03, and its verification is `LOCAL`: the hub's own data.

**Stop 5. The manifest, as the edge receives it.** Ask the hub's NATS server the same question the edge asks:

```bash
uv run python - <<'EOF'
import asyncio, json, os
import nats
from sentinel.crdt import codec

async def main():
    nc = await nats.connect(os.environ["HUB_NATS"])
    reply = await nc.request("sync.hub.manifest", codec.encode({"from": "reader", "known": None}), timeout=5)
    print(len(reply.data), "bytes of CBOR;", dict(reply.headers))
    manifest = codec.decode(reply.data)
    for summary in manifest:
        if not summary["e"].startswith("omm:"):
            print(json.dumps(summary, indent=1))
    print(sum(s["e"].startswith("omm:") for s in manifest), "element-set summaries")
    await nc.close()

asyncio.run(main())
EOF
sha256sum $CDMS/EX-DIL-0[123]-*.cdm | cut -c1-16
```

One conjunction summary with the keys from the table in stop 5, beside the element-set summaries the pass module offers. The three entries in `c` are the first 16 digits of each file's sha256, oldest first. `pc` is a log10, and `h` is the start of the inputs hash `assess` printed.

**Stop 6. The edge.** Watch the edge's list every 2 s:

```bash
for i in $(seq 30); do curl -s $EDGE/api/events | python3 -c "import json,sys; print([(e['verification'], e['cdm_count']) for e in json.load(sys.stdin)])"; sleep 2; done
```

First an empty list, then `('HUB_ASSERTED', 3)`: the summary has arrived and names three CDMs, none of them here. Then `('VERIFIED', 1)`: the latest record arrived first, was re-assessed on the edge and matched. Then the count climbs to 3 as the history arrives. (If you lingered over stop 5, the early states may already be past.) The loop ends after a minute; Ctrl-C ends it sooner. Then look at the arrival log and the event's history:

```bash
curl -s $EDGE/api/sync | python3 -c "
import json, sys
for a in json.load(sys.stdin)['arrivals']:
    if not a['event_id'].startswith('omm:'):
        print(a['class'], a['latest'], a['sha'], a['hash_ok'], a['verification'])"
EVENT=$(curl -s $EDGE/api/events | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['event_id'])")
curl -s $EDGE/api/events/$EVENT | python3 -c "
import json, sys
for h in json.load(sys.stdin)['history']:
    print(h['message_id'], h['source'], h['sha256'][:16])"
curl -s -X POST -H 'Content-Type: application/json' -d '{"preset": "CONNECTED"}' $EDGE/api/demo/link; echo
```

The arrivals read `P1_URGENT True`, then two `P4_BULK False`, every one `hash_ok` True. Every CDM in the history has source `sync:hub`. The last command restores the link.

**Stop 7. Decide with the link down.** Cut the link and watch the edge measure it:

```bash
curl -s -X POST -H 'Content-Type: application/json' -d '{"preset": "DENIED"}' $EDGE/api/demo/link; echo
for i in $(seq 15); do curl -s $EDGE/api/link | python3 -c "import json,sys; m=json.load(sys.stdin)['monitor']; print(m['state'], m['seconds_since_success'])"; sleep 1; done
```

For a few seconds the state keeps its last reading: DEGRADED, or LIMITED if nothing large has crossed since stop 6 ("How it fails" explains why). It turns DENIED once 8 s pass with no success. Now act on both sides:

```bash
curl -s -X POST -H 'Content-Type: application/json' -H 'X-Sentinel-Operator: maj.ortiz@edge-alpha' \
     -d '{"decision": "MANEUVER", "rationale": "RED inside the planning window"}' \
     $EDGE/api/events/$EVENT/decision | python3 -m json.tool
curl -s -X POST -H 'Content-Type: application/json' -H 'X-Sentinel-Operator: maj.ortiz@edge-alpha' \
     -d '{"field": "triage_status", "value": "MANEUVER_PLANNING"}' $EDGE/api/events/$EVENT/annotation > /dev/null
curl -s -X POST -H 'Content-Type: application/json' -H 'X-Sentinel-Operator: capt.lee@hub' \
     -d '{"field": "triage_status", "value": "WATCH"}' $HUB/api/events/$EVENT/annotation > /dev/null
curl -s --data-binary @$(ls $CDMS/EX-DIL-04-*.cdm) $HUB/api/ingest/cdm; echo
curl -s $EDGE/api/events | python3 -m json.tool | grep -E '"(latest_message_id|verification)"'
```

The decision comes back at once, from the edge alone: dot `["edge-alpha", 1]`, an `event_ref` naming EX-DIL-03, `signature_valid` true, `review_required` false. The hub accepts EX-DIL-04. The edge still shows EX-DIL-03 as VERIFIED: it has no way to know better, and its LINK reads DENIED. Now reconnect and compare the two nodes' operator data:

```bash
curl -s -X POST -H 'Content-Type: application/json' -d '{"preset": "CONNECTED"}' $EDGE/api/demo/link; echo
sleep 5
curl -s $HUB/api/ops/digest | python3 -m json.tool | grep -E '"(log|annotations)"'
curl -s $EDGE/api/ops/digest | python3 -m json.tool | grep -E '"(log|annotations)"'
curl -s $EDGE/api/events/$EVENT/ops | python3 -m json.tool | grep -E '"(kind|message_id|review_required|v|conflict)"'
curl -s $EDGE/api/events | python3 -m json.tool | grep -E '"(latest_message_id|verification)"'
```

The two digests are equal: the same state on both nodes. The decision still names EX-DIL-03 and now reads `review_required: true`. The last `message_id`, the event's `current_ref`, names EX-DIL-04. `triage_status` holds both values with `conflict: true`. The event itself is EX-DIL-04, VERIFIED. The same `/ops` call on `$HUB` shows the same.

**Stop 8. The console and the stream.** Open `$EDGE` (http://127.0.0.1:8141) in a browser and select the event. Check each item listed in stop 8 of the walkthrough, then open the Sync tab to see the queue and the arrivals. To see the doorbell, stream the edge's events in a third terminal:

```bash
curl -sN --max-time 15 http://127.0.0.1:8141/api/stream
```

and post the last update to the hub from terminal 2:

```bash
curl -s --data-binary @$(ls $CDMS/EX-DIL-05-*.cdm) $HUB/api/ingest/cdm; echo
```

The stream shows `sync.progress` every cycle, then `cdm.accepted` (the edge ingested EX-DIL-05) and `sync.arrival` (the agent logged it, with `hash_ok` and `verification`). In the browser the band turns AMBER with `worst RED` and the DILUTED chip. Resolve the conflict by clicking a status on either console; a `RESOLUTION` entry appears in the log on both nodes.

**Clean up.** Ctrl-C in terminal 1 stops all five processes and deletes their state; `rm -r $CDMS` removes the files.

**The same path in one process.** `tests/sync/test_hub_edge.py` drives a hub and an edge over one in-process bus, with a frozen clock:

```bash
uv run pytest tests/sync/test_hub_edge.py -v
```

Each test name is one claim of this chapter: summaries small enough to send first, HUB-ASSERTED before any CDM, latest before history, VERIFIED after a full sync, conflicts kept, REVIEW REQUIRED once superseded.

## Design choices

**The bytes' hash is the CDM's identity** (the technical guide, "Data flow of a CDM").
- *Buys:* idempotent ingest on every route, fetch by a short prefix, and an end-to-end check that what arrived is what was announced.
- *Costs:* any change to the bytes, even a comment, makes a new record and a new update of the event.
- *Rejected:* no ADR records this choice. The obvious alternative, the CDM's `MESSAGE_ID`, is chosen by the source, and nothing stops a source from reusing one.

**The first node to ingest a CDM names the event, and the name travels (ADR-008).**
- *Buys:* updates fetched out of order, history after the latest, still land in one event.
- *Costs:* an edge cannot group updates differently from its hub.
- *Rejected:* re-deriving the event at the edge from the pair and TCA, which splits an event when updates arrive out of order.

**The edge re-assesses instead of trusting the hub (ADR-008).**
- *Buys:* a VERIFIED chip means the edge's own engine reproduced the number. A bug, a different engine version or a different policy on the hub shows as MISMATCH.
- *Costs:* the edge runs the full engine on every CDM, and both nodes must run the same engine and policy to verify.
- *Rejected:* taking the hub's numbers as the edge's own, which is what replicating the hub's results would do. ADR-008's "Buys" states the difference: numbers the edge has checked, not trusted.

**Summaries first, then records by deadline (ADR-006).**
- *Buys:* the whole picture in seconds, and the urgent record before the backlog. The LIMITED results in [`docs/ddil-results.md`](../ddil-results.md) measure both.
- *Costs:* summaries spend link time before any record, and an event whose record cannot arrive in time is held SUMMARY-ONLY.
- *Rejected:* arrival order, which the same scenario measures as the baseline.

**Reference data is pulled; operator data is merged (ADR-005, ADR-008).**
- *Buys:* CDMs, which are immutable and authored upstream, get ordered delivery. Decisions, which are authored concurrently offline, get a merge that loses nothing and shows conflicts.
- *Costs:* two mechanisms to maintain.
- *Rejected:* one mechanism for both, whether a stream mirror (FIFO, no merge) or last-writer-wins (silently loses work).

**Console events never cross the link (ADR-009).**
- *Buys:* the edge's console cannot show a hub number before the edge has verified it.
- *Costs:* each console sees only its own node.
- *Rejected:* one shared subject space, which NATS leafnodes would propagate by default.

The ADRs are in [`docs/system-design.md`](../system-design.md), each opening with what it buys, measured where a number exists, and what it costs.

## How it fails

Walk the stops again, this time with something wrong at each.

| Stop | What goes wrong | What the code does | Where it shows |
|---|---|---|---|
| 1, 4 | The same file is posted twice | `ingest` finds the hash and returns `duplicate`, HTTP 200. Nothing is stored or published again | The reply |
| 2, 4 | A position labelled `[m]` (`sed 's/\[km\]/[m]/'` on the file) | `CdmRejected`: quarantined with `WRONG_UNIT`, HTTP 422, and announced on `node.hub.cdm.rejected` | `GET /api/quarantine`; the console's live feed |
| 3 | The model does not apply (no covariance, low relative speed, curvilinear uncertainty) | `Method.REFUSED` with the reason; the event is still stored and synced, and its summary carries `r` | Band UNASSESSED ("NO PC"), "Pc refused" and the reason chip |
| 4, 5 | A CDM quarantined on the hub | It never enters the manifest, so the edge never hears of it | Only on the node that received it: `GET /api/quarantine` there |
| 5, 6 | A summary the edge cannot display | Skipped with `Hub summary rejected` or `Manifest entry skipped`; the rest apply | The edge's log |
| 6 | Tampered bytes, or a reply naming another event | `Sync record refused` with `hash_mismatch` or `item_id_mismatch`; retried after 1, 2, 4 … 32 pulls; the records behind it still come | The edge's log; the event stays HUB-ASSERTED or UPDATING |
| 6 | The link cannot deliver the record before its deadline | `SUMMARY_ONLY`: the link is not spent on it | `summary_only` in `GET /api/sync`; the Sync tab |
| 6 | The edge computes a different result | MISMATCH; `Hub assertion not reproduced` names the fields | The MISMATCH chip; the edge's log; `engine_version` in `GET /api/node` on both nodes |
| 7 | The link is cut | Exchanges fail; the state is *measured* DENIED; local writes still succeed | The LINK chip; `GET /api/link` |
| 7 | A peer's entries are unsigned or from an untrusted node | Rejected before merge and recorded once | `rejected` in `GET /api/ops/digest` |
| 8 | The stream drops | The console marks "no stream", reconnects, and refetches everything on open | The status dot in the top bar |

Two behaviours you will meet in this walk are worth knowing before they surprise you:

- **VERIFIED is not "current".** With the link down, the edge verified the last manifest it received. The LINK chip is what tells the operator the picture may be stale.
- **A thin reading can outlive a thin link.** `LinkMonitor` measures throughput only on transfers of 2,000 bytes or more. After LIMITED is lifted, a quiet link with nothing large to move keeps reading LIMITED until a big transfer is measured. A reconnect after DENIED starts the measurement afresh.

## Check yourself

1. The same EX-DIL-03 file is uploaded to the hub twice, once by curl and once by a script. What changes on the hub and on the edge?
   <details><summary>Answer</summary>Nothing. The sha256 of the bytes is already stored, so `ConjunctionService.ingest` returns `duplicate` (HTTP 200) before parsing. Nothing is published, the manifest's digest does not change, and the edge's next manifest request gets `Sentinel-Unchanged`.</details>

2. Why does the edge's console never receive the hub's `cdm.accepted` message for EX-DIL-03, and what would break if it did?
   <details><summary>Answer</summary>Console events are published on `node.hub.>`, and the edge's leaf configuration denies importing `node.>` (ADR-009). If they crossed, the edge would show the hub's numbers the moment the hub computed them, before the edge had fetched the bytes and reproduced the result. The HUB-ASSERTED/VERIFIED distinction would be meaningless.</details>

3. Mid-sync, the edge shows the event VERIFIED with `cdm_count` 1 while the hub shows 3. Is that a contradiction?
   <details><summary>Answer</summary>No. The latest record is P1_URGENT and was fetched first; the two older ones are P4_BULK history, still queued. VERIFIED is about the hub's latest record only, and the count is the number of CDMs the edge holds.</details>

4. Someone changes `amber_pc` in the hub's `ConjunctionPolicy` and not the edge's. What does the edge show for EX-DIL-05, and why is that the right outcome?
   <details><summary>Answer</summary>MISMATCH, if the change moves EX-DIL-05's band or worst-case band. The edge bands its own assessment with its own policy, and `disagreements` compares `b` and `w` with the hub's assertion. The engine version would not reveal this, because it hashes `AssessmentConfig`, not the policy. Two nodes sorting the same Pc differently is exactly what an operator must be told.</details>

5. After reconnect, which node flags the offline decision REVIEW REQUIRED first, and why can they differ for a moment?
   <details><summary>Answer</summary>Usually the hub. The flag is computed on read from each node's own `current_ref`. The hub already holds EX-DIL-04, so the decision is flagged there as soon as the exchange merges it. The edge flags it only after it has fetched EX-DIL-04, later in the same cycle or the next one.</details>

6. Both operators acted while partitioned. Why are the two triage statuses a CONFLICT, but the edge's decision and a hypothetical hub decision would not be?
   <details><summary>Answer</summary>A triage status is a register: one value per field, so two concurrent writes compete, and the multi-value register keeps both and flags them. Decisions are entries in a grow-only log: two decisions are simply two entries, each signed and ordered for display by (lamport, node, seq). Nothing is overwritten, so there is nothing to conflict.</details>

7. A hub bug starts serving EX-DIL-02's bytes when asked for EX-DIL-03's sha16. What does the edge do, and what does the operator see?
   <details><summary>Answer</summary>`_is_the_record_asked_for` fails: the bytes' sha256 does not start with the sha16 asked for. The edge logs `Sync record refused` with `hash_mismatch`, puts the record back with back-off, and keeps fetching the records behind it. The operator sees the event stay HUB-ASSERTED (or UPDATING), never a VERIFIED built on the wrong bytes.</details>

8. The summary carries Pc as a log10 rounded to three decimals. How does that affect verification?
   <details><summary>Answer</summary>`disagreements` re-encodes the edge's result with `compact_summary`, the same function and rounding the hub used, then compares. A difference big enough to change a rounded value is a MISMATCH; noise smaller than the rounding step is hidden, unless it happens to straddle a rounding boundary. The same code on the same bytes gives the same floats, so in practice a MISMATCH means different inputs, engine or policy. The summary stays small enough to send first.</details>

## Where next

- Back to the parts, now that you have seen them together: [2, the risk engine](02-risk-engine.md); [3, CDMs and events](03-cdm-and-events.md); [4, the node and its API](04-node-and-api.md); [5, the console](05-console.md); [6, the bus and the link](06-bus-and-links.md); [7, priority sync](07-priority-sync.md); [8, operator data](08-operator-data.md); [9, the DDIL harness](09-ddil-harness.md), which runs this same path under every link preset.
- The contracts this path must keep: [`docs/icd/sync-envelope.md`](../icd/sync-envelope.md) (the summary, priority classes, headers and verification states), [`docs/icd/asyncapi.yaml`](../icd/asyncapi.yaml) (every subject and what may cross the leaf), [`docs/icd/cdm-profile.md`](../icd/cdm-profile.md) (every admission code).
- The measurements: [`docs/ddil-results.md`](../ddil-results.md), and [`docs/demo-script.md`](../demo-script.md) for the same story told to an operator.
