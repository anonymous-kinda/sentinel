# Sentinel technical guide

For an engineer who has just cloned the repository and needs to understand it, run it and change it correctly.

The other design documents answer different questions:
- `docs/system-design.md` holds the architecture decisions (ADR-001 to ADR-012) and the alternatives each one rejected. It says *why*.
- `docs/risk-engine-design.md` holds the collision-probability maths and the test ladder. It says *what the engine computes*.
- This guide says *how the code is put together*: where things live, how data moves, how to run each configuration, and which files and tests you touch to extend it.

Where this guide and the code disagree, the code is right and this guide is a bug. `tests/docs/test_technical_guide.py` checks the configuration reference, the quoted import contracts, and every path, `make` target and `sentinel` subcommand named here against the repository. Every number quoted from a generated report or a test is registered in `tests/doc_claims.toml`, so `tests/test_docs.py` fails when the source moves.

## Contents

1. [Architecture](#architecture)
2. [Data flow of a CDM](#data-flow-of-a-cdm)
3. [The sync layer](#the-sync-layer)
4. [The AI assistant pipeline](#the-ai-assistant-pipeline)
5. [The pass module and element sets over sync](#the-pass-module-and-element-sets-over-sync)
6. [Configuration reference](#configuration-reference)
7. [Running it](#running-it)
8. [The test ladder and test layout](#the-test-ladder-and-test-layout)
9. [How to extend](#how-to-extend)
10. [Generated files](#generated-files)
11. [Troubleshooting](#troubleshooting)

## Architecture

### One node, three roles

Sentinel is a modular monolith (ADR-004). One Python package, `sentinel`, runs as one process, the *node*. The node serves its own API and console (ADR-009), so an operator's screen never depends on the link to another node. The role is configuration, not a separate build:

| Role | `SENTINEL_ROLE` | Bus | Sync | Element sets at start | Where it runs |
|---|---|---|---|---|---|
| standalone | `standalone` (default) | in-process, unless `SENTINEL_NATS_URL` is set | none | the vendored public snapshot | a laptop, a single enclave, the public read-only node |
| hub | `hub` | its own `nats-server`, which listens for leafnodes | `SyncServer` answers manifest, fetch and operator-data requests | the vendored public snapshot | the cloud or an operations centre |
| edge | `edge` | its own `nats-server`, holding one leafnode link to the hub | `SyncAgent` pulls from the hub named by `SENTINEL_HUB_ID` | none: they arrive from the hub through sync | a deployed node on a DDIL link |

`SENTINEL_ELEMENTS` overrides the snapshot for any role (`_element_snapshot` in `sentinel/api/app.py`).

A deployed node is two processes, `nats-server` and `sentinel`. The node talks only to its *local* NATS server; the server, not the application, holds the link to other nodes. A denied link therefore never breaks the node (ADR-004). JetStream is not used (ADR-004, ADR-008).

The composition root is `sentinel/api/app.py`. `build_node` creates the clock, the bus, the conjunction store and service, the operator-data service, the link monitor and the element store, which it loads from the role's snapshot. It also decides which element sets this node offers edges (`SENTINEL_SYNC_ELEMENTS`). The `lifespan` hook then:
1. swaps the in-process bus for NATS when `SENTINEL_NATS_URL` is set (`LateBus`, `sentinel/bus/inprocess.py`);
2. builds the node's sync records (`_sync_records`): conjunction CDMs by default, element sets under the `omm:` prefix, behind one `CompositeRecords`;
3. starts `SyncServer` on a hub, or `SyncAgent` on an edge that has a hub id;
4. loads the NASA CARA reference library and starts the exercise feeder, if enabled;
5. runs any `startup` hooks that extensions put in `node.extensions`.

Routers beyond the conjunction core are registered through `REGISTRARS` in `sentinel/api/extensions.py`: the AI assistant (`sentinel/api/ai_routes.py`), the pass module (`sentinel/api/pass_routes.py`) and demonstration-mode screening (`sentinel/api/screening_routes.py`). A registrar may add its module name to `node.extensions["modules"]`; `GET /api/node` reports the list, and the console shows a feature tab only for a module the node reports (`web/src/extensions.tsx`, `web/src/features.tsx`). A registrar may also add hooks: the pass module registers an `elements_changed` hook, which the element records call when a synced element set changes the store.

### Modules and their allowed dependencies

```
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │ entry points      cli   cli_ext                                              │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │ node assembly     api   (composition root: settings, routes, SSE, wiring)    │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │ decision support  ai    (tools receive the services they read by injection)  │
 ├─────────────────────────────────────┬────────────────────────────────────────┤
 │ mission modules                     │ mission-agnostic platform              │
 │   conjunction   passes   screening  │   sync   ops                           │
 │   validation                        │                                        │
 ├─────────────────────────────────────┼────────────────────────────────────────┤
 │ seams on open standards             │ core                                   │
 │   cdm        (CCSDS 508.0-B-1 CDM)  │   bus   triage   crdt                  │
 │   ephemeris  (CCSDS 502.0-B-3 OEM)  │   linkstate   audit                    │
 │   adapters   (one source each)      │                                        │
 ├─────────────────────────────────────┴────────────────────────────────────────┤
 │ foundations       risk (pure maths)   clock   obs                            │
 └──────────────────────────────────────────────────────────────────────────────┘
   Imports point down, or sideways inside one column. The right-hand column
   never imports the left-hand one; the contracts below forbid most of those
   edges, and the paragraph after them names the ones they do not.
```

The imports that actually exist between packages (measured with grimp, the graph library under import-linter, at the commit this guide was written against):

| Package | Imports |
|---|---|
| `api` | ai, audit, bus, cdm, clock, conjunction, linkstate, obs, ops, passes, risk, screening, sync, validation |
| `cli`, `cli_ext` | api, cdm, conjunction, obs, passes, risk, screening |
| `ai` | obs, ops |
| `conjunction` | bus, cdm, clock, risk, triage |
| `passes` | bus (the service's `passes.updated`), clock, ephemeris, obs, triage |
| `screening` | cdm, obs, passes (the element store) |
| `validation` | cdm, risk |
| `sync` | bus, clock, crdt, linkstate, obs, triage |
| `ops` | bus, clock, crdt |
| `cdm` | risk (to build a `risk.Conjunction`) |
| `ephemeris` | cdm (the CCSDS time parser only), obs |
| `adapters` | ephemeris, obs |
| `bus` | obs |
| `risk`, `crdt`, `triage`, `linkstate`, `audit`, `clock`, `obs` | nothing inside `sentinel` |

`.importlinter` is the source of truth for what is *allowed*, and `uv run lint-imports` enforces it in CI. Its contracts, quoted:

| Contract id | Name (verbatim) | Source modules | Forbidden |
|---|---|---|---|
| `risk-pure` | The risk engine is pure maths: no I/O, transport, web or storage | `sentinel.risk` | fastapi, nats, sqlite3, httpx |
| `core-is-mission-agnostic` | The core (bus, triage) knows nothing about any mission module | `sentinel.bus`, `sentinel.triage` | sentinel.conjunction, sentinel.risk, sentinel.cdm, sentinel.api, sentinel.passes |
| `cdm-is-a-seam` | The CDM codec (ADR-001 seam) does not depend on services above it | `sentinel.cdm` | sentinel.conjunction, sentinel.api, sentinel.bus |
| `sync-is-mission-agnostic` | Sync, CRDTs and operator data know nothing about any mission module | `sentinel.sync`, `sentinel.crdt`, `sentinel.ops`, `sentinel.linkstate` | sentinel.conjunction, sentinel.risk, sentinel.cdm, sentinel.api, sentinel.passes |
| `ai-does-no-math` | The AI layer has no path to the maths: it asks tools, never computes | `sentinel.ai` | sentinel.risk, sentinel.cdm, numpy, scipy |
| `hosted-ai-at-the-edges` | Hosted AI SDKs are confined to their adapters | `sentinel.ai.assistant`, `sentinel.ai.catalog`, `sentinel.ai.grounding`, `sentinel.ai.narrate`, `sentinel.ai.policy`, `sentinel.ai.router`, `sentinel.ai.tools` | typesafe_sdk, anthropic |
| `passes-is-independent` | The pass module knows nothing about conjunction risk, sync internals or the API | `sentinel.passes` | sentinel.risk, sentinel.cdm, sentinel.conjunction, sentinel.sync, sentinel.api, sentinel.ai |
| `ephemeris-and-adapters-are-independent` | Ephemeris codecs and source adapters know nothing about risk, CDM services, conjunction, sync, the API or AI | `sentinel.ephemeris`, `sentinel.adapters` | sentinel.risk, sentinel.cdm, sentinel.conjunction, sentinel.sync, sentinel.api, sentinel.ai (one ignored import: `sentinel.ephemeris.oem -> sentinel.cdm.timefmt`) |
| `ephemeris-is-below-passes` | Ephemeris tables sit below the pass module and the adapters that feed them | `sentinel.ephemeris` | sentinel.passes, sentinel.adapters |
| `screening-never-decides-pc` | Screening produces element-set geometry; only the engine decides a Pc | `sentinel.screening` | sentinel.risk, sentinel.conjunction, sentinel.api, sentinel.sync, sentinel.ai |
| `passes-offline` | The pass engine computes at the edge: no network, transport or web stack | `sentinel.passes` | httpx, nats, fastapi, uvicorn |

The two core contracts forbid the conjunction module, the risk engine, the CDM codec, the pass module and the API. They do not name `sentinel.screening`, `sentinel.ephemeris`, `sentinel.adapters` or `sentinel.ai`. Nothing in the core imports those today (the import table above), but only a contract line would keep it that way.

### Seams and extension points

| Seam | Protocol or registry | Implementations |
|---|---|---|
| Transport | `Bus` in `sentinel/bus/base.py` | `InProcessBus`, `NatsBus`, `LateBus` |
| Reference data for sync | `ReferenceRecords` in `sentinel/sync/records.py` | `ConjunctionRecords` (`sentinel/conjunction/sync_adapter.py`), `ElementRecords` (`sentinel/passes/sync_adapter.py`), `CompositeRecords` (`sentinel/api/records.py`) |
| Mission-agnostic priority | `TriageKey` in `sentinel/triage/__init__.py` | built by each mission module |
| Pass prediction | `PassProvider` in `sentinel/passes/model.py` | `SkyfieldProvider`, `TabulatedEphemerisProvider` |
| The provider a node uses | `ProviderFactory` in `sentinel/passes/service.py` (element sets in, provider out) | `SkyfieldProvider` by default |
| AI routing | `Router` in `sentinel/ai/router.py` | `DeterministicRouter`, `JevRouter` (`sentinel/ai/router_jev.py`) |
| AI phrasing | `Narrator` in `sentinel/ai/narrate.py` | `TemplateNarrator`, `ClaudeNarrator` (`sentinel/ai/narrate_claude.py`) |
| Time | `Clock` in `sentinel/clock.py` | `RealClock`, `SimClock`, `FixedClock` |
| Trace evidence | `EvidenceIndex` in `mbse/evidence.py` | pytest ids, harness scenarios, import contracts, CI steps |
| HTTP routes | `REGISTRARS` in `sentinel/api/extensions.py` | AI, pass and screening routes |
| Node hooks | `node.extensions` keys `startup`, `shutdown`, `elements_changed`, `modules` | the pass module's `elements_changed` |
| CLI subcommands | `register` in `sentinel/cli_ext.py` | `serve`, `exercise generate`, `screen` |
| Console tabs | `registerTab` in `web/src/extensions.tsx` | Sync, Assistant and Passes tabs in `web/src/features.tsx` |

## Data flow of a CDM

A CDM enters a node by one of five routes, and every route goes through the same function, `ConjunctionService.ingest` in `sentinel/conjunction/service.py`:

| Route | Source label | Data class passed in |
|---|---|---|
| `POST /api/ingest/cdm` (body: KVN bytes, at most 1,000,000 bytes) | `api-upload` | REAL |
| `POST /api/screening` (`sentinel/api/screening_routes.py`, `docs/icd/screening-api.md`): each close approach from the node's element sets, as a CDM with no covariance | `api-screening` | DERIVED |
| The exercise feeder (`_exercise_feeder` in `sentinel/api/app.py`), releasing scripted CDMs as the clock reaches them | `exercise-feed` | EXERCISE |
| The NASA CARA reference library, loaded at start-up from `fixtures/cara/PcTestCaseCDMs/` | `nasa-cara-library` | REAL |
| An edge fetching from its hub (`SyncAgent._fetch`) | `sync:<hub_id>` | whatever the hub's `Sentinel-Data-Class` header says |

A screened approach needs no special case in the engine. It is an ordinary DERIVED CDM without covariance, so the existing `NO_COVARIANCE` gate refuses its Pc (ADR-002).

```
 raw bytes
   │
   ├─ sha256 already stored? ───────────── yes ─► "duplicate" (HTTP 200); nothing else happens
   ▼
 parse KVN                 sentinel/cdm/kvn.py        fails ─► quarantine PARSE_ERROR
   ▼
 admit and convert         sentinel/cdm/validate.py   wrong ─► quarantine with the code
                           sentinel/cdm/to_conjunction.py      (WRONG_UNIT, UNSUPPORTED_REF_FRAME,
   │                                                             PARTIAL_COVARIANCE, ...)
   │  incomplete ─► CdmWarning kept with the CDM (COVARIANCE_ABSENT, UNIT_LABEL_ANOMALY)
   ▼
 data class                ORIGINATOR=SENTINEL-EXERCISE ─► EXERCISE; SENTINEL-SCREENING ─► DERIVED
   ▼
 group into an event       same object pair and TCA within 60 s; or the id the hub assigned
   ▼
 store the raw bytes       sentinel/conjunction/store.py (SQLite; raw bytes are the source of truth)
   ▼
 assess                    sentinel/risk/engine.py assess(); cached per (sha256, engine version)
   ▼
 publish                   node.<id>.cdm.accepted.<event_id>  ─► /api/stream (SSE) ─► console
   ▼
 views on request          triage band, worst case, maneuver commit point, consequence
                           (sentinel/conjunction/policy.py); summaries for edges
                           (sentinel/conjunction/summaries.py)
```

Step by step:

1. **Idempotency.** The SHA-256 of the raw bytes is the CDM's identity. A second copy is a no-op.
2. **Parse.** `sentinel/cdm/kvn.py` reads CCSDS 508.0-B-1 KVN into a `CdmMessage`. Anything that is not a CDM is quarantined as `PARSE_ERROR`; a `ValueError` or `KeyError` later in conversion is quarantined as `UNREADABLE`.
3. **Admission** follows the repository's ingest rule, and `docs/icd/cdm-profile.md` lists every code. Input that would make the answer *wrong* raises `CdmRejected` with a stable code, and the message is quarantined (`GET /api/quarantine`) and announced on `node.<id>.cdm.rejected`. Input that makes it *incomplete* is accepted with a `CdmWarning`, stored beside the CDM. `sentinel/cdm/validate.py` lists which is which: for example a state labelled in metres is wrong, and a missing covariance is incomplete (the engine will refuse a Pc for it).
4. **Data class.** Every CDM is REAL, DERIVED or EXERCISE. Sentinel's own generators mark their output at the source, and the mark wins over the route it arrived by (`ORIGINATOR_DATA_CLASS` in `sentinel/conjunction/service.py`).
5. **Events.** CCSDS CDMs carry no event id, so the rule is explicit: the same primary and secondary with a TCA within 60 s is the same event. The node that first ingests a CDM assigns the id, and it travels with the record (`Sentinel-Event-Id`); an edge never re-derives it (ADR-008).
6. **Assessment.** `risk.assess()` never raises on bad data. It returns `Method.REFUSED` with a `RefusalReason` and the value that tripped the gate. Results are cached per CDM hash and *engine version*, which is `sentinel.__version__` plus a hash of `AssessmentConfig`; changing a threshold re-assesses from the raw bytes rather than trusting old numbers.
7. **Publish.** The service publishes the event summary on the node-local subject `node.<id>.cdm.accepted.<event_id>`, with the header `Sentinel-Kind: cdm.accepted`.
8. **Console.** `GET /api/stream` subscribes to `node.<id>.>` and forwards each message as a server-sent event named by its `Sentinel-Kind`. The console (`web/src/api/client.ts`, `useStream`) bumps a version counter on each event and refetches what it shows. Node-local subjects never cross a leaf link (ADR-009).
9. **Triage** happens when a view is built, not at ingest. `sentinel/conjunction/policy.py` bands the Pc (RED at 1e-4 or more, AMBER at 1e-5 or more, GREEN below, UNASSESSED when refused), adds the band of `pc_max` when the result is diluted, sets the maneuver commit point to TCA minus 8 h, and derives a consequence level. These are operator assumptions and are labelled as such. `GET /api/events` sorts active events by time to the maneuver commit point.
10. **Sync.** On a hub, `ConjunctionService.manifest()` reduces every active local event to a compact summary for edges. The next section follows it across the link.

In the console, a Pc renders only through `web/src/components/PcValue.tsx`, which takes the whole assessment object. A refusal can never render as a zero, and a diluted Pc always shows its worst case.

## The sync layer

Reference data (CDMs and public element sets) moves hub to edge by an application-level priority pull (ADR-006, ADR-008). Operator data moves both ways as state-based CRDTs (ADR-005). Both run over request/reply on the `Bus`, so the same code runs in-process in `tests/sync/` and over NATS leafnodes in the harness.

### Subjects

Defined in one place, `sentinel/bus/subjects.py`:

| Subject | Direction | Content |
|---|---|---|
| `node.<node_id>.>` | node-local only | console events: `cdm.accepted`, `cdm.rejected`, `ops.changed`, `sync.progress`, `sync.arrival`, `link.state`, `link.emulation`, `passes.updated` |
| `sync.<hub_id>.manifest` | edge asks hub | compact summaries of every active event (CBOR) |
| `sync.<hub_id>.fetch` | edge asks hub | one record's original bytes |
| `ops.<hub_id>.exchange` | both ways in one request/reply | CRDT anti-entropy |

The edge's leafnode remote denies exporting `unit.>`, `passes.>` and `node.>`, and denies importing `node.>` (`deploy/nats/edge.conf.tmpl`). `tests/compliance/test_deploy_conformance.py` pins that list.

### One sync cycle

`SyncAgent.cycle()` in `sentinel/sync/agent.py`, every `SENTINEL_SYNC_INTERVAL_S` seconds:

1. **Operator data first.** One request carries this node's CRDT contexts and everything the hub was last known to lack (`OpsService.payload_for`). The reply carries everything this node lacks. The hub's contexts are remembered in SQLite (`ops_peers`). A stale memory only means sending more, so a lost reply costs nothing but bytes.
2. **Manifest.** The request carries the digest of the last manifest seen. If nothing changed, the hub answers with `Sentinel-Unchanged: 1` and no body. Otherwise `put_summaries` stores the summaries, and the console shows every event as `HUB_ASSERTED` within seconds, before any full CDM has arrived.
3. **Want list.** The set difference between the manifest's records and this node's, ordered by the mission-agnostic triage key (`sentinel/triage/__init__.py`): class, then earliest deadline, then higher consequence. The agent reads only four fields of a summary:

   | Field | Meaning |
   |---|---|
   | `e` | item id |
   | `dl` | deadline, epoch seconds (for a conjunction, the maneuver commit point) |
   | `q` | consequence, 0 to 3 |
   | `c` | records: `[[sha256 prefix (16 hex), size in bytes, created epoch], ...]`, the last one being the latest |

   The latest record of an item with consequence SERIOUS or higher, due inside the urgent window (72 h by default), is `P1_URGENT`. Any other latest record is `P2_ROUTINE`. Superseded history is `P4_BULK`.
4. **Admission control.** In `edf` mode, if the measured link cannot deliver an item's latest record before its deadline, the item is marked `SUMMARY_ONLY` instead of spending the link on it.
5. **Fetch and verify.** Each record is fetched by hash prefix and handed to the module's `ingest`. For conjunctions, the edge re-assesses the CDM locally and compares its own inputs hash with the one the hub asserted. The event's verification becomes `VERIFIED` when they agree and `MISMATCH` when they do not; `UPDATING` means the hub holds a newer CDM this node has not fetched yet. Each arrival is published as `sync.arrival`.

Each request's timeout scales with the link the agent has measured: `6 + 1.5 × bytes / max(rate, 400)` seconds. A cycle spends at most `max(5 × interval, 10)` seconds pulling.

`SENTINEL_SYNC_MODE=fifo` orders the want list by hub arrival time and turns admission control off. It exists only as the measured baseline for the LIMITED scenario. In the latest run (`docs/ddil-results.md`), on the same link with the same bytes, every event was visible as a summary at 5.5 s, and the most urgent full CDM arrived in 12.1 s with earliest-deadline-first against 46.8 s in FIFO order.

**Element sets share the link.** A hub offers edges the element sets the pass module uses: by default only the 38 in the imaging catalog (`SENTINEL_SYNC_ELEMENTS=catalog`), not every set it holds. Each record costs a request/reply and a manifest entry on a thin link. ADR-008 describes what offering the whole snapshot cost in a development run, how to reproduce it, and why the fix (batched fetch, or a reference-data class below routine CDMs) is an open question rather than done. The DDIL numbers above were measured with the catalog on offer.

A summary is small enough to send first. Without its record list, every summary in the test scenario encodes to at most 256 bytes of CBOR: the bound is `SUMMARY_MAX_BYTES` in `sentinel/conjunction/summaries.py`, asserted by `tests/sync/test_hub_edge.py::test_summaries_are_small_enough_to_send_first`.

The full contract of this layer is written down and held to the code. `docs/icd/sync-envelope.md` specifies the summary fields, priority classes, headers and verification states. `docs/icd/asyncapi.yaml` specifies every subject, header and payload on the bus, and what may cross the leaf link.

### Link state is measured

`LinkMonitor` in `sentinel/linkstate/monitor.py` classifies the link from what the sync agent observes, never from a flag:

| State | Condition |
|---|---|
| UNKNOWN | no exchange attempted yet |
| DENIED | no success for more than 8 s, with a failure since |
| LIMITED | measured throughput under 4,000 bytes/s |
| DEGRADED | round trip of 1 s or more, or a recent failure |
| CONNECTED | otherwise |

Round trip and throughput are exponentially weighted (α = 0.3). Throughput is measured only on transfers of 2,000 bytes or more. A link that comes back after DENIED is measured afresh. The AI tier policy and admission control both read this state.

### Operator data: CRDTs

`sentinel/crdt/` holds the data types; `sentinel/ops/service.py` persists and exchanges them:

- **Decision log** (`SignedLog`, `sentinel/crdt/log.py`): a grow-only set of immutable entries, each Ed25519-signed by its node and hash-chained per node, encoded as canonical CBOR (`sentinel/crdt/codec.py`). An entry from an untrusted node or with a bad signature is rejected before merge and counted. The same dot arriving with different content raises `IntegrityError`.
- **Annotations** (`MVMap`, `sentinel/crdt/mvmap.py`): multi-value registers for `triage_status`, `assignee` and `note`. Concurrent writes are all kept and shown as a CONFLICT. A person resolves one by writing a value that supersedes both, and that write appends a signed `RESOLUTION` entry to the log naming the field, the new value and every value it superseded (`tests/test_ops_log.py`). The log's entry kinds are `DECISION`, `NOTE` and `RESOLUTION` (`ENTRY_KINDS`).
- **REVIEW REQUIRED.** Every decision records the CDM it was made against. If a newer CDM for that event has arrived since, the decision is flagged `review_required`. The ops service asks the conjunction module through a callback (`current_ref`), so it never imports a mission module.
- **Trust.** Each node creates its key at `<SENTINEL_VAR>/keys/<node_id>.ed25519.pem` on first start. Without `SENTINEL_TRUST_FILE`, a node trusts only itself: it can author entries but will not merge anyone else's.

The property tests in `tests/property/test_crdt.py` drive three replicas through random histories over a network that drops, duplicates and reorders. They assert convergence, no loss, no silent overwrite and visible conflicts.

## The AI assistant pipeline

The assistant (ADR-007) routes an operator's request to one catalogued tool, lets code compute the facts, and phrases them. `sentinel/ai/assistant.py`:

```
 text ─► router (Jev | deterministic) ─► Route: tool, arguments, confidence
      ─► gate ─────────────────────────► ask back if confidence < 0.5, or an event tool has no event
      ─► tool (sentinel/ai/tools.py) ──► facts: every number from Sentinel's own services
      ─► narrator (Claude | template) ─► prose
      ─► grounding guard ──────────────► an AI answer stating a number the facts lack is withheld;
                                         the template answer is shown, naming the number
      ─► audit (sentinel/audit/chain.py) one hash-chained JSON line per ask and per confirm
```

| Part | File | Notes |
|---|---|---|
| Tool catalog | `sentinel/ai/catalog.py` | `list_events`, `get_assessment`, `explain_dilution`, `link_status`, `sync_queue`, `draft_decision`. The descriptions are also Jev's option criteria. |
| Tools | `sentinel/ai/tools.py` | deterministic code over the conjunction, ops, link and sync services. Dates and hours are formatted here, by code. A tool that writes returns a draft. |
| Deterministic router | `sentinel/ai/router.py` | slash commands at confidence 1.0, keyword rules at 0.6 |
| Jev router | `sentinel/ai/router_jev.py` | model pinned to `jev-1.13.0`. Typed Choice questions whose options are exactly the catalog and this node's events; one attempt, no retries |
| Template narrator | `sentinel/ai/narrate.py` | always available; tested grounded on every tool and exercise event |
| Claude narrator | `sentinel/ai/narrate_claude.py` | model pinned to `claude-opus-5`; no retries |
| Tier policy | `sentinel/ai/policy.py` | a pure function of the measured link, the marking and operator opt-in |
| Grounding guard | `sentinel/ai/grounding.py` | numbers must match, at the precision stated, a number in the facts or the question. Numbers glued to units are checked too. |
| Eval | `sentinel/ai/evaluation.py`, `sentinel/ai/calibration.py`, `scripts/ai_eval.py` | routers scored through the same gate on `evals/routing.jsonl` |
| HTTP | `sentinel/api/ai_routes.py` | `GET /api/ai/status`, `POST /api/ai/ask`, `POST /api/ai/confirm`, `GET /api/ai/audit`, `GET /api/ai/audit/verify` |

**Tier policy.** Hosted AI needs a marking that starts with UNCLASSIFIED and operator opt-in (`SENTINEL_AI_CLOUD=1`). Then:

| Measured link | Router | Narrator |
|---|---|---|
| CONNECTED, DEGRADED | Jev, if `TYPESAFE_API_KEY` is set | Claude, if `ANTHROPIC_API_KEY` is set |
| LIMITED | Jev, if configured | template |
| DENIED, UNKNOWN | deterministic | template |

An edge measures its hub link and uses that as the WAN state. A hub or standalone node has no upstream link to measure; it is treated as CONNECTED, and `/api/ai/status` says the state is assumed. A hosted call that fails for any reason falls back to the local tier inside the same answer, and the answer lists the fallback.

**Hosted SDKs load lazily.** A provider is loaded only when its key variable is set, and its SDK is imported only then (`_load_provider` in `sentinel/api/ai_routes.py`). A bundle built without the `ai` extra serves the local tier.

**Drafts, not actions.** `draft_decision` returns a draft id. `POST /api/ai/confirm` turns it into a signed `DECISION` entry once, carrying router, confidence, model and the audit sequence of the ask. It is refused with HTTP 409 if the CDM the draft was made against has been superseded since. A read-only node answers questions but never records.

**Audit.** The log lives at `<SENTINEL_VAR>/ai-audit.jsonl`. `GET /api/ai/audit/verify` recomputes the chain and reports the first bad line.

## The pass module and element sets over sync

`sentinel/passes/` answers one question for a ground unit: when can a catalogued imaging satellite see it, and when can none? It runs on the edge node that serves the unit's operator, from public element sets that node already holds. The HTTP contract is `docs/icd/passes-api.md`; this section covers the code behind it.

### The pieces

| File | Role |
|---|---|
| `sentinel/api/pass_routes.py` | The HTTP surface, exactly as `docs/icd/passes-api.md` specifies: the unit (GET, PUT, DELETE), windows and gaps for 1 to 72 h, the catalog, and ground tracks for the globe. Registers the `passes` module and the `elements_changed` hook. |
| `sentinel/passes/service.py` | `PassService`: one unit per node, its windows and gaps, cached; publishes the coordinate-free `passes.updated` |
| `sentinel/passes/unit.py` | Validates a unit (`UnitRejected` names the field and never echoes a value) and keeps it in one private file (`UnitFile`) |
| `sentinel/passes/tracks.py` | Earth-fixed positions every 20 s for the console globe, at most 30 min per request; visualization only |
| `sentinel/passes/model.py` | The shared contract: `Unit`, `Imager`, `PassWindow`, `PassProvider`, `ImagerNotCovered` |
| `sentinel/passes/imaging.toml`, `sentinel/passes/catalog.py` | Public EO and SAR imagers; each field of regard is a cited planning assumption that errs wide. Wrong input raises `CatalogError`. |
| `sentinel/passes/elements.py` | Loads a CelesTrak OMM snapshot; pairs it with the catalog and returns every imager it skipped, with the reason |
| `sentinel/passes/geometry.py` | Mask elevation from the field of regard, sun elevation, the element-age timing pad, stale after 3 days |
| `sentinel/passes/topocentric.py` | The unit on the WGS84 ellipsoid |
| `sentinel/passes/providers/skyfield_local.py` | `SkyfieldProvider` (`skyfield-local`): SGP4 through Skyfield, bundled timescale only |
| `sentinel/passes/providers/skyfield_passes.py` | Refines Skyfield's rise and set to a millisecond, on the side that widens the window |
| `sentinel/passes/providers/tabulated.py` | `TabulatedEphemerisProvider` (`tabulated-ephemeris`): interpolates an Earth-fixed `StateTable`; never extrapolates |
| `sentinel/passes/gaps.py` | Gaps between padded, usable windows. The label is `GAP_LABEL`, "not observed by catalogued imagers" |
| `sentinel/passes/element_store.py` | Element sets as records: one OMM object per record, canonical JSON bytes, admission with named reasons. Its `version` counts accepted sets, so results can be cached against it. |
| `sentinel/passes/sync_adapter.py` | `ElementRecords`: the pass module's side of `ReferenceRecords` |

### How a pass request is answered

`GET /api/passes?hours=24` calls `PassService.passes` (`sentinel/passes/service.py`):

1. **No unit, no answer.** Without a unit the route returns 409. The unit is set with `PUT /api/passes/unit` and validated by `unit_from_dict`: latitude in [-90, 90], longitude in [-180, 180], a positive reaction time and a non-blank id; anything else is 422, naming the field.
2. **Pair the catalog with this node's element sets** (`match_catalog`). An imager with no usable element set is skipped and reported under `catalog.skipped`, and then every gap is marked `low_confidence`: a missing imager makes gaps look longer than they are.
3. **Ask the provider** for every window over `[start, start + hours]`, where `start` is the current minute, floored. The provider is built from the node's element sets by a `ProviderFactory`, `SkyfieldProvider` by default.
4. **Find the gaps** between padded, usable windows (`sentinel/passes/gaps.py`), then the first gap at least the unit's reaction time long that is still to run (`next_unobserved`).

Steps 2 and 3 are cached against the unit, the element store's `version`, the start minute and the hours (16 entries). Step 4 is recomputed on every call, because the cached start can be up to a minute behind now. An element set that SGP4 cannot use for a catalogued imager returns 503 rather than an answer with that imager silently missing.

When a synced element set changes the store, the service publishes one `node.<id>.passes.updated` once the burst has settled for a second. The message carries a reason and the store version: no unit id and no coordinates. The console refetches on it.

### Providers

Providers follow one convention (`PassProvider` in `sentinel/passes/model.py`): return every pass that overlaps `[start, end]` with its true rise, culmination and set, sorted by rise. An imager the provider has no data for raises `ImagerNotCovered`; it is never skipped, because a dropped imager makes every gap look longer than it is (ADR-011). The conformance suite holds both providers to that contract and to a brute-force Skyfield oracle: rise and set within 2 s, maximum elevation within 0.1° (`tests/conformance/test_pass_providers.py`).

Tabulated ephemerides come from a CCSDS OEM (`sentinel/ephemeris/oem.py`), from sampling a propagator (`sentinel/ephemeris/tabulate.py`), or from a source adapter. The one adapter today is for Wayfinder, a product of Privateer Space, on an *assumed* schema that has not been validated against the real API. Sentinel is not affiliated with or endorsed by Privateer Space; see `docs/adapters/wayfinder.md`.

A gap is "not observed by catalogued imagers", never "safe". `tests/passes/test_wording.py` parses the module's source and fails on the word.

### OPSEC: the unit never leaves its edge

ADR-010 enforces this in four independent layers:

| Layer | In the code |
|---|---|
| Data model | Nothing implements `ReferenceRecords` for the unit or its passes, so sync cannot carry them |
| Application | The only bus message is `node.<id>.passes.updated`, with no id and no coordinates; the service logs `Unit set` and `Unit cleared` with no fields; `UnitRejected` never echoes a submitted value |
| Storage | One file, `<SENTINEL_VAR>/unit.json`: mode 0600, replaced atomically, never written to SQLite or the audit log (`UnitFile` in `sentinel/passes/unit.py`) |
| Transport | The edge's leafnode denies exporting `unit.>`, `passes.>` and `node.>` (`deploy/nats/edge.conf.tmpl`) |

The OPSEC harness scenario (`harness/opsec.py`, `harness/scenarios.py`, `make opsec`) runs real hub and edge processes and captures every message the hub's `nats-server` carries. It checks that no message holds the unit in any encoding it could travel in, that canaries on the denied subjects never reach the hub, and that no hub file holds the unit. Controls show that none of those negatives is vacuous. The recorded run is in `docs/ddil-results.md`.

### Element sets over sync

A hub or standalone node loads the vendored CelesTrak snapshot at start-up; an edge loads none and receives them from its hub (`SENTINEL_ELEMENTS` overrides either). `ElementRecords` offers each element set to the sync layer under an item id prefixed `omm:`, with the moment it goes stale (epoch plus 3 days) as its deadline and ROUTINE consequence. `CompositeRecords` in `sentinel/api/records.py` routes records between modules by that prefix. CDMs and element sets therefore travel through one `SyncServer` and `SyncAgent`, and `sentinel/sync` did not change to carry them (ADR-008).

A hub offers only the imaging catalog's element sets unless `SENTINEL_SYNC_ELEMENTS=all`. It still holds every set, because its own screening uses them.

`tests/sync/test_modules_share_sync.py` proves three things: both modules arrive intact, every urgent CDM is queued ahead of every element set, and element summaries never appear in the conjunction view. `tests/api/test_node_elements.py` covers what each role loads and offers.

## Configuration reference

Every node setting is an environment variable read at start-up; `sentinel/api/settings.py` is the main reader (12-factor, systemd-friendly). A boolean is true when its value is `1`, `true`, `yes` or `on` (any case); any other value is false. The deployment templates that set these are `deploy/bundle/install.sh`, `deploy/ansible/roles/sentinel/templates/sentinel.env.j2`, `deploy/containers/Dockerfile` and `harness/cluster.py`.

### Node

| Variable | Default | Effect |
|---|---|---|
| `SENTINEL_NODE_ID` | `standalone` | The node's identity: its subject namespace (`node.<id>.>`), its signing-key file name, the default operator (`operator@<id>`) |
| `SENTINEL_ROLE` | `standalone` | `hub` starts `SyncServer`; `edge` starts `SyncAgent` when `SENTINEL_HUB_ID` is set. The node reports the `sync` module only when it runs one of them. Any value other than `hub`, `edge` or `standalone` stops the node at start-up with `ValueError`. |
| `SENTINEL_HUB_ID` | unset | Edge only: the hub to sync from. Without it an edge runs no sync agent. |
| `SENTINEL_NATS_URL` | unset | This node's own `nats-server`, for example `nats://127.0.0.1:4222`. Unset means the in-process bus. The node retries the connection 60 times at 0.5 s intervals, then fails to start. |
| `SENTINEL_SYNC_MODE` | `edf` | Edge only: `edf` (earliest deadline first, with admission control) or `fifo` (the measured baseline). Any other value stops the edge at start-up with `ValueError`. |
| `SENTINEL_SYNC_INTERVAL_S` | `2.0` | Edge only: seconds between sync cycles |
| `SENTINEL_DB` | `:memory:` | SQLite file for CDMs, assessments and operator data. The default keeps nothing across restarts. |
| `SENTINEL_VAR` | `var` (relative to the working directory) | Writable state: `keys/<node_id>.ed25519.pem`, `keys/<node_id>.pub`, `ai-audit.jsonl` and the unit file `unit.json` (mode 0600). Under systemd it must point inside the writable prefix (`tests/test_deploy_env.py`). |
| `SENTINEL_TRUST_FILE` | unset | JSON map of node id to Ed25519 public key (hex). Unset: the node trusts only itself and merges no one else's decision entries. |
| `SENTINEL_MARKING` | `UNCLASSIFIED // EXERCISE` | Classification banner shown in the console. Hosted AI is allowed only when it starts with `UNCLASSIFIED`. |
| `SENTINEL_EXERCISE` | on | Run the scripted exercise scenario (`sentinel/conjunction/exercise.py`); its CDMs carry `ORIGINATOR=SENTINEL-EXERCISE` |
| `SENTINEL_LIBRARY` | on | Load NASA CARA's 53 operational conjunctions as REAL reference events at start-up |
| `SENTINEL_READ_ONLY` | off | Public node: ingest, screening, operator writes, setting or clearing the unit, and AI confirmation return HTTP 403 |
| `SENTINEL_WEB_DIST` | `web/dist` in a source checkout, if built; else unset | Directory of the built console, served at `/`. Unset: API only. |
| `SENTINEL_FIXTURES` | `fixtures/` in a source checkout | Root of the reference data: the CARA library and validation cases, and the vendored element-set snapshot (`omm/celestrak-resource-20260924.json`) that nodes and `sentinel screen` load by default. An installed bundle sets it to `<prefix>/fixtures`. |
| `SENTINEL_ELEMENTS` | unset | Path of a CelesTrak OMM JSON snapshot to load at start-up. Unset: a hub or standalone node loads the vendored snapshot under `SENTINEL_FIXTURES`, and an edge loads none and receives element sets from its hub. A missing file is logged (`Element snapshot missing`) and the node starts with no element sets. |
| `SENTINEL_SYNC_ELEMENTS` | `catalog` | Which element sets this node offers edges over sync: `catalog` (only the imagers in `sentinel/passes/imaging.toml`) or `all` (every set it holds). Any other value stops the node at start-up with `ValueError`. |
| `SENTINEL_AI` | on | Register the assistant's routes. Off: `/api/ai/status` returns `{"enabled": false}`. |
| `SENTINEL_AI_CLOUD` | off | Operator opt-in to hosted AI (Jev routing, Claude phrasing). The tier policy still requires an UNCLASSIFIED marking and a usable measured link. |
| `SENTINEL_DEMO_CONTROLS` | off | Enable `POST /api/demo/link`, accepted from localhost only, which applies Toxiproxy link presets. For demonstrations and the harness. |
| `SENTINEL_TOXIPROXY_API` | unset (the control then uses `http://127.0.0.1:8474`) | Toxiproxy's API, for link emulation |
| `SENTINEL_CLOCK` | `real` | `real`; `sim:<ISO-8601 epoch>,<scale>` (starts at the epoch and runs `<scale>` times wall speed); `fixed:<ISO-8601 instant>`. The epoch or instant may be `now`. The console labels a non-real clock. |

### Logging

| Variable | Default | Effect |
|---|---|---|
| `SENTINEL_LOG_FORMAT` | `text` | `json` writes one JSON object per line (the container sets it); anything else writes `key=value` text |
| `SENTINEL_LOG_LEVEL` | `INFO` | Root log level for `sentinel serve` when `--log-level` is not given, and for the scripts that call `configure_logging()` without a level (`scripts/trace.py`, `scripts/oscal_evidence.py`, `scripts/sysml_check.py`, `scripts/sbom.py`, `scripts/scan.py`). The flag wins over the variable; `deploy/systemd/sentinel.service` passes `--log-level warning`. |

### Installer and offline signature verification

Read by `deploy/bundle/install.sh` and `deploy/bundle/verify_signature.sh`, which `make airgap-verify`, `deploy/bundle/verify_offline.sh` and the Ansible role all use. Set either the key or the keyless variables, never both; both, or neither, is refused.

| Variable | Default | Effect |
|---|---|---|
| `SENTINEL_ROLE` | `standalone` | Also read by `install.sh`, which writes it into the new `<prefix>/sentinel.env` |
| `SENTINEL_VERIFY_KEY` | unset | Key mode: the PEM public key the bundle must be signed with (a site key, or the throwaway key of `make sign-local`) |
| `SENTINEL_TRUSTED_ROOT` | unset | Keyless mode: the Sigstore `trusted_root.json` to verify against, offline |
| `SENTINEL_TRUSTED_ROOT_SHA256` | unset | Keyless mode, optional: the pinned digest of that trusted root, checked first |
| `SENTINEL_CERT_IDENTITY` | unset | Keyless mode: the exact signing identity, the release workflow at its tag |
| `SENTINEL_CERT_ISSUER` | `https://token.actions.githubusercontent.com` | Keyless mode: the OIDC issuer of that identity |

### Other environment variables

These are not `SENTINEL_*` but change behaviour:

| Variable | Read by | Effect |
|---|---|---|
| `TYPESAFE_API_KEY` | `sentinel/api/ai_routes.py`, `scripts/ai_eval.py` | Enables the Jev router; `make ai-eval` runs Jev only when it is set |
| `ANTHROPIC_API_KEY` | `sentinel/api/ai_routes.py`, via the Anthropic SDK | Enables the Claude narrator |
| `SOURCE_DATE_EPOCH` | `scripts/build_bundle.py` | Timestamp stamped into the bundle; default is the commit time, which makes the tarball reproducible |
| `PREFIX`, `SYSTEMD`, `PYTHON` | `deploy/bundle/install.sh` | Install location (default `/opt/sentinel`), whether to install and start the systemd unit (default `1`), the Python 3.12 interpreter to use |
| `COSIGN` | `deploy/bundle/verify_signature.sh` | The cosign binary (default: `cosign` on `PATH`) |

`make` variables (`ARCH`, `PRIMARY`, `HOURS`, `VERIFY_KEY`, `CERT_IDENTITY`, `XCCDF`) are documented in `make help` and the `Makefile`.

## Running it

Every command in this section was run on this commit in a fresh worktree (WSL2, Python 3.12, Node 22), except four, which are marked: `make ddil`, `make opsec`, the hosted-AI command and the AWS deployment. Commands that download from GitHub, PyPI or npm say so.

### Set up

```bash
export PATH=$HOME/.local/bin:$PATH          # uv lives here
uv venv --python 3.12                       # 3.12: the lock resolves numpy differently on newer Pythons
uv pip install -e ".[dev]"                  # PyPI
npm --prefix web ci                         # npm registry; only for the console and web tests
make help                                   # every make target
```

`make install` runs the virtual-environment, Python install and `npm ci` steps in one go.

### Standalone node

```bash
make serve                   # builds web/dist, then: uv run sentinel serve --port 8000
```

Open http://127.0.0.1:8000. The node loads the NASA reference library and plays the exercise scenario. `uv run sentinel serve` alone starts the API without building the console.

For console work, `make dev` runs the API on :8000 and the Vite dev server with hot reload on :5173, proxying `/api` to the node.

The CLI works without a node:

```bash
uv run sentinel assess fixtures/cara/PcTestCaseCDMs/000025994_conj_000037558_20210324_151047_20210323_154356.cdm
uv run sentinel cdm parse fixtures/cara/SampleCDMs/AlfanoTestCase01.cdm     # structure and admission warnings
uv run sentinel exercise generate --out /tmp/exercise                       # the scenario as KVN files
make screen PRIMARY=40115                                                   # demonstration mode: geometry, no Pc
uv run python scripts/dilution_demo.py
```

`sentinel assess` exits 0 when a message was assessed (a refusal is still an assessment), 2 when it was rejected as wrong, and 1 on usage or I/O errors.

To push a CDM into a running node:

```bash
curl -X POST --data-binary @fixtures/cara/PcTestCaseCDMs/000025994_conj_000037558_20210324_151047_20210323_154356.cdm \
     http://127.0.0.1:8000/api/ingest/cdm
```

The reply is 201 when accepted, 200 for a duplicate and 422 when quarantined.

The pass and screening APIs (`docs/icd/passes-api.md`, `docs/icd/screening-api.md`), with the exercise unit from the ICD:

```bash
curl -X PUT -H 'Content-Type: application/json' \
     -d '{"unit_id": "EX-UNIT-1", "lat_deg": 35.26, "lon_deg": -116.68, "alt_m": 700, "reaction_time_min": 30}' \
     http://127.0.0.1:8000/api/passes/unit
curl 'http://127.0.0.1:8000/api/passes?hours=24'                   # windows, gaps, next unobserved gap
curl -X POST -H 'Content-Type: application/json' -d '{"primary_norad_id": 40115}' \
     http://127.0.0.1:8000/api/screening                            # geometry only; each approach becomes a DERIVED CDM
curl -X DELETE http://127.0.0.1:8000/api/passes/unit
```

The unit is stored in `<SENTINEL_VAR>/unit.json` until it is deleted.

Hosted AI, with your own keys. Not run for this guide: it needs accounts with both providers and network access to them.

```bash
SENTINEL_AI_CLOUD=1 TYPESAFE_API_KEY=... ANTHROPIC_API_KEY=... make serve
```

### Local hub and edge

Two nodes on one machine, each with its own `nats-server`, joined by a leafnode link that Toxiproxy shapes. No containers.

```bash
make demo-local              # hub http://127.0.0.1:8000, edge http://127.0.0.1:8001; Ctrl-C stops both
```

`make demo-local` depends on `make tools`, which downloads every binary pinned in `deploy/tools.lock` for the host architecture from GitHub, sha256-verified, into `.tools/`. The demo needs only two of them:

```bash
uv run python scripts/fetch_tools.py nats-server toxiproxy     # GitHub download
uv run python -m harness.demo                                  # what demo-local runs
```

On the edge's console, the LINK chip applies Toxiproxy presets to the real leaf connection. `docs/demo-script.md` is a shot-by-shot walk-through; the short sequence (CONNECTED, DENIED, LIMITED, CONNECTED) is in the docstring of `harness/demo.py`.

### The DDIL harness

`harness/` runs named scenarios on a real two-node cluster (`harness/cluster.py`): two `nats-server` processes, Toxiproxy on the leaf link, two Sentinel nodes. Each scenario asserts measured properties and writes `harness/results/<scenario>.json`.

```bash
uv run python -m harness.run recovery                  # one scenario; needs nats-server and toxiproxy in .tools/
uv run python -m harness.run denied --denial-s 60      # a longer denial
make ddil                                              # all six, then rewrites docs/ddil-results.md
make opsec                                             # the OPSEC scenario; rewrites docs/ddil-results.md only if all six have results
```

The scenarios are `denied`, `limited`, `intermittent`, `degraded`, `recovery` and `opsec` (`harness/scenarios.py`). Each runs the hub's default configuration: the hub loads the vendored element sets and offers edges the imaging catalog, so conjunction CDMs and element sets share the link.

`python -m harness.report` writes `docs/ddil-results.md` from all six results in `harness/results/` or not at all: with any missing, it names them, writes nothing and exits 1. `make opsec` passes `--if-complete`, so after one scenario on a fresh clone it says what is missing, leaves the report alone and succeeds. Commit the report only from a complete, passing run of all six (`make ddil`).

For this guide, `recovery` and `opsec` were run through `python -m harness.run`, which writes only the git-ignored `harness/results/`. `recovery` passed. `opsec` failed one assertion, not from a leak but from a harness race: it counted element sets on the hub-side capture, which subscribes after the leaf connects and so could miss an early fetch. The scenario now counts them from the edge's own sync record (`SyncLedger` in `harness/opsec.py`) and keeps the capture for leak detection only. `make ddil` was not run, because it rewrites the committed report.

### The air-gap bundle

One tarball per CPU architecture installs a node with no network (`scripts/build_bundle.py`, `deploy/bundle/install.sh`).

```bash
make bundle ARCH=x86_64      # dist/sentinel-<version>-x86_64.tar.gz; wheels from PyPI, uv and nats-server from GitHub
make airgap-local            # build, sign with a throwaway key, verify, install and run inside unshare -rn
make airgap-selftest         # real cosign: tampered, unsigned, wrong-key and wrong-identity bundles are refused
```

`make airgap-local` and `make airgap-selftest` download cosign and the other supply-chain tools from GitHub the first time (`make supply-tools`), and need unprivileged user namespaces for `unshare -rn`. The same tools run the SBOM and vulnerability gates:

```bash
make sbom                    # SPDX and CycloneDX SBOMs into dist/sbom/ (PyPI for the staged runtime)
make scan                    # Trivy on what ships, reviewed VEX applied; any finding left fails (downloads Trivy's database)
```

`make airgap-local` passed on this commit. Its install check (`deploy/bundle/verify_offline.sh`) requires the node it installed to reproduce the NASA validation offline: 53 operational events, a worst relative error below 1e-6 and no false negatives.

To install a bundle by hand, without systemd:

```bash
tar -xzf sentinel-<version>-x86_64.tar.gz && cd sentinel-<version>-x86_64
PREFIX=$HOME/sentinel SYSTEMD=0 ./install.sh
```

`install.sh` checks `SHA256SUMS` first, installs every dependency from `wheels/` with `--no-index --require-hashes`, and writes `<prefix>/sentinel.env` if absent. Verify the signature before unpacking, with `make airgap-verify VERIFY_KEY=<public key>` or, for a release, `CERT_IDENTITY=<signing workflow>` (`docs/supply-chain.md`). For an operator at a disconnected site, `docs/install-guide.md` is the one-page procedure.

### The cloud hub

`docs/deploy-aws.md` covers Terraform (`deploy/aws/terraform/`) and Ansible (`deploy/ansible/`). It needs an AWS account and was not run for this guide. CI checks the Terraform and the playbook syntax without AWS.

## The test ladder and test layout

```bash
uv run pytest -q                  # the whole suite; must report 0 skipped
uv run pytest -q -m tier3         # one rung of the risk-engine ladder
uv run pytest -q tests/conformance
npm --prefix web test             # the console (vitest)
make test                         # pytest, then the web tests
make lint                         # ruff, lint-imports, then the TypeScript check
```

`pyproject.toml` runs pytest with `--disable-socket --allow-unix-socket`, so a test that opens a network socket fails. The only exception is `@pytest.mark.enable_socket` on a test that binds loopback ports (`tests/test_harness_ports.py`). Skyfield uses its bundled timescale only.

### The ladder

The risk engine was built down the ladder in `docs/risk-engine-design.md` section 7, one rung at a time, each failing before the code that satisfied it. Each rung is a pytest marker:

| Marker | File | What it establishes |
|---|---|---|
| `tier1` | `tests/test_tier1_geometry.py` | Frame rotation and encounter-plane geometry; no probability |
| `tier2` | `tests/test_tier2_integration.py` | The collision integral against closed forms and an independent `scipy.integrate.dblquad` oracle |
| `tier3` | `tests/test_tier3_cara_validation.py` | Agreement with NASA CARA's published cases, the gate against CARA's own verdicts, and the vendored files' checksums |
| `tier4` | `tests/test_tier4_dilution.py` | Maximum Pc and dilution detection, including inflating a covariance until Pc falls and the flag sets |
| `tier5` | `tests/test_tier5_refusal.py` | Every refusal path, each carrying the value that tripped it |
| `tier6` | `tests/test_tier6_contract.py` | The output contract: no Pc without its method, no dilution flag without `pc_max`, a stable inputs hash |

Expected values come from closed forms or from files NASA published, transcribed by hand with provenance (`fixtures/cara/PROVENANCE.md`, `scripts/transcribe_cara_fixtures.py`). None is produced by running this code.

### What each directory proves

| Directory | What it proves |
|---|---|
| `tests/` (top-level files) | The ladder; the CDM codec and admission policy (`tests/test_cdm_codec.py`); link-state measurement; structured logging and the constant-message policy, checked by parsing the source (`tests/test_obs.py`, `tests/test_logging_policy.py`); that every deployment environment sets `SENTINEL_VAR`; the harness (no port handed out twice, which element sets each node starts with, and an OPSEC leak detector that finds the unit in every encoding); that every workflow action is pinned by commit SHA (`tests/test_workflows_pinned.py`) |
| `tests/api/` | The node over HTTP with a frozen clock: sorting by commit point, every Pc with its method, idempotent ingest and quarantine, the read-only node, the same-origin CSP, the assistant's API, the pass API against `docs/icd/passes-api.md`, the screening API, and which element sets each role holds and offers |
| `tests/sync/` | The hub/edge protocol over an in-process bus: summaries first and small, earliest deadline first, verification, operator data both ways, REVIEW REQUIRED, and two modules over one unmodified sync layer |
| `tests/property/` | CRDT convergence, no loss and no silent overwrite under drop, duplication and reordering (Hypothesis) |
| `tests/ai/` | Every assistant guard: tier policy, confidence gate, grounding, drafts and confirm-once, the audit chain. The Jev and Claude adapters run their real SDKs against mock transports, with no network or key. |
| `tests/passes/` | The catalog, element sets, geometry, providers, gaps, the end-to-end pipeline over the exercise day, the pass service (one unit, cached answers, nothing published but `passes.updated`), the unit file, ground tracks, and the "never safe" wording policy |
| `tests/conformance/` | Every `PassProvider` against one contract and a brute-force Skyfield oracle |
| `tests/ephemeris/` | The OEM codec, `StateTable` admission, interpolation and tabulation |
| `tests/adapters/` | The Wayfinder adapter on its assumed schema, with the fixture re-derived from the public element set |
| `tests/screening/` | Demonstration-mode screening against brute force, and the DERIVED CDM that the engine refuses |
| `tests/supplychain/` | The tools lock, checksums, SBOMs, Trivy and VEX handling, bundle manifests, and `verify_signature.sh`'s policy against a stub cosign |
| `tests/compliance/` | The OSCAL generator, its sources and citations, the STIG role, deployment-config conformance, and that the committed OSCAL documents are what the sources generate |
| `tests/mbse/` | The SysML reader, the evidence indexes, the trace generator, and that `docs/traceability.md` is current with no broken reference |
| `tests/docs/` | Every interface control document against the code, both ways: the OpenAPI export is current and every route documented; the AsyncAPI document matches the subjects, headers and leaf policy, and every message real nodes send validates against it; the CDM profile matches the codec's codes, frames and units; the sync envelope matches `sentinel/sync`, `sentinel/triage` and the adapters. The program documents: every white-paper proof-point number is registered against a generated report, and the SVG quad chart gets the Markdown drift guards. Also this guide, `docs/index.md` and `CONTRIBUTING.md`: variables, `make` targets, CLI subcommands, import contracts, paths and the document list |
| `tests/test_docs.py`, `tests/doclint.py`, `tests/doc_claims.toml` | The drift guard for `README.md`, `CLAUDE.md`, `SECURITY.md` and `docs/`: every path, `make` target and `sentinel` subcommand exists, every package has a docstring, and every registered headline number matches its generated source at the precision stated |
| `web/src/__tests__/` | The console: `PcValue`'s contract, formatting, the API client, the assistant panel and the passes views |

Evidence outside pytest: `uv run lint-imports` (import contracts), `docs/ddil-results.md` (the harness on real processes), `make airgap-local` and `make airgap-selftest` (offline install and signature proofs), and the CI steps in `.github/workflows/`.

## How to extend

Each recipe lists the files to touch and the tests or contracts that will hold you to it. Write the failing test first (`CONTRIBUTING.md`).

### (a) A mission module that syncs through `ReferenceRecords`

The goal is a module whose reference data crosses the link by priority without a line of `sentinel/sync` changing. `sentinel/passes/sync_adapter.py` is the worked example.

1. **The module.** Create `sentinel/<module>/`. Reduce each item to the generic triage fields; do not import `sentinel.sync`, `sentinel.api` or another mission module.
2. **Its records.** Add `sentinel/<module>/sync_adapter.py` with a class satisfying `ReferenceRecords` (`sentinel/sync/records.py`):
   - `manifest()` returns one summary per item: `e` is the item id with a prefix of your own (the pass module uses `omm:`), `dl` the deadline in epoch seconds, `q` the consequence 0 to 3, `c` the records, latest last.
   - `get(sha16)` returns the raw bytes and the headers `Sentinel-Sha256`, `Sentinel-Event-Id` and `Sentinel-Data-Class`.
   - `has`, `put_summaries` and `async ingest(raw, source, data_class, item_id)`, which returns `{status, sha256, verification}`.

   Priority follows from `dl` and `q` alone: a latest record with consequence 2 or more, due inside the urgent window, is `P1_URGENT`.
3. **Compose it.** `CompositeRecords(default, {prefix: records})` in `sentinel/api/records.py` routes by item-id prefix. Add your prefix and records to the map in `_sync_records` in `sentinel/api/app.py`, beside `omm:`. That is the only node change. If the node must hold or offer only some of your records, follow `_load_elements` and `_offered_elements` in the same file.

   Offer edges only what they use. Every record costs a request/reply and a manifest entry on a thin link, and competes with urgent CDMs there. Read ADR-008, "Reference data on a thin link", and measure with the harness before a hub offers more.
4. **Report it.** Add a registrar to `REGISTRARS` in `sentinel/api/extensions.py` that mounts the module's routes and appends its name to `node.extensions["modules"]`, as `sentinel/api/pass_routes.py` does. If the module must react when sync changes its data, add a hook to `node.extensions` and call it from your records' `ingest`, as `elements_changed` does. Register the console tab with `registerTab` in `web/src/features.tsx`, keyed on the same module name.
5. **Contracts.** In `.importlinter`, add a contract forbidding your module from importing `sentinel.sync`, `sentinel.api` and the other mission modules, as `passes-is-independent` does. Add your package to the forbidden list of `sync-is-mission-agnostic` and `core-is-mission-agnostic`.
6. **Tests.** Follow `tests/sync/test_modules_share_sync.py`: both modules arrive intact through one unmodified agent, urgent CDMs are queued ahead of your routine records, and your summaries never leak into the conjunction view. Then check your branch left the core closed (`CLAUDE.md`, "The core stays closed to modules"):

   ```bash
   git diff --stat main -- sentinel/sync sentinel/bus sentinel/crdt sentinel/triage     # must print nothing
   ```

   The pass module's proof of the same property is a fixed commit range, `git diff --stat 67199b7 f16e294 -- sentinel/sync sentinel/bus sentinel/crdt sentinel/triage`, which prints nothing. The core changes only deliberately: a bug fix proven by a failing test, typing or documentation with no behaviour change, or a design change recorded in an ADR.
7. **Interface control documents.** Each interface you add goes in `docs/icd/`, and `uv run pytest -q tests/docs` holds you to it:
   - your item-id prefix and any header your records set go in `docs/icd/sync-envelope.md`. `tests/docs/test_sync_envelope.py` finds every class under `sentinel/` that defines the `ReferenceRecords` methods, and every prefix given to `CompositeRecords`, so it fails on your header or prefix until the document lists it. Keep the prefix a string constant or literal it can read;
   - a new node-local event kind or bus header goes in `docs/icd/asyncapi.yaml`. `tests/docs/test_asyncapi.py` finds kinds at the `subjects.local` call sites, and fails on any it cannot find in the document;
   - a new route needs a tag from `sentinel/api/apidoc.py`, a `summary=` and a docstring, which becomes its description; `tests/docs/test_openapi_current.py` checks all three on every route except the pass module's. Then run `make openapi` to regenerate `docs/icd/openapi.json`.
8. **OPSEC.** Anything that must never leave the edge is not a record. If it travels on the bus, give it a subject the leaf denies (`deny_exports` in `deploy/nats/edge.conf.tmpl`) and add it to the list `tests/compliance/test_deploy_conformance.py` checks.
9. **Harness.** If the module changes what crosses the link, add a scenario to `SCENARIOS` in `harness/scenarios.py` and to the matrix in `.github/workflows/harness.yml`.
10. **Trace.** Add the requirement and its evidence (recipe e).

### (b) A pass provider under `tests/conformance`

1. **The provider.** Add `sentinel/passes/providers/<name>.py` with a class that has a `name` and `windows(unit, imagers, start, end) -> list[PassWindow]` (`PassProvider` in `sentinel/passes/model.py`):
   - return every pass that overlaps the interval with its true rise, culmination and set, sorted by rise;
   - raise `ImagerNotCovered` for an imager your data does not cover; never skip it;
   - set `sunlit` for EO and leave it `None` for SAR; report `element_age_days` honestly, because it drives the timing pad and the stale flag.
2. **No network inside the provider.** The `passes-offline` contract forbids httpx, nats, fastapi and uvicorn in `sentinel.passes`, and `passes-is-independent` forbids sync and the API. A provider backed by an external service gets its data elsewhere (an adapter, or the sync layer) and receives a `StateTable` or element sets, as `TabulatedEphemerisProvider` does.
3. **Conformance.** Add a factory to `tests/conformance/factories.py` that builds your provider from a `Scenario`'s public element sets. Add one `pytest.param(factories.<factory>, id="<name>")` line to `PROVIDER_FACTORIES` in `tests/conformance/test_pass_providers.py`. Every conformance test then runs against it, including the oracle checks.
4. **Run it.**

   ```bash
   uv run pytest -q tests/conformance
   uv run lint-imports
   ```
5. **Use it on a node.** `PassService` builds its provider from the node's element sets through a `ProviderFactory` (`sentinel/passes/service.py`); `register` in `sentinel/api/pass_routes.py` takes the default, `SkyfieldProvider`. A provider built from element sets plugs in there as `provider_factory=`. A provider that needs other inputs, such as the `StateTable`s `TabulatedEphemerisProvider` reads, needs those inputs on the node first; no node wiring for tables exists yet. `tests/passes/test_service.py` shows the service with an injected factory.
6. **Trace.** Name the new conformance tests as evidence of VC-PASS-005 in `mbse/verification.sysml` if the provider is part of a requirement (recipe e).

### (c) A source adapter

For ephemerides, `sentinel/adapters/wayfinder.py` is the pattern.

1. **Parse bytes, do not fetch them.** Add `sentinel/adapters/<source>.py` with a function from the source's payload to a `StateTable` (`sentinel/ephemeris/table.py`). It is the only code that knows the source's shape. An API client (keys, rate limits, retries) belongs in its own module.
2. **Admit by the shared rules.** Call `require_earth_fixed` and `require_utc`. Raise `EphemerisRejected` with a stable code for anything that would make the answer wrong; the `StateTable` constructor already rejects bad shapes, non-finite numbers, naive times and non-increasing epochs. Log each parse with a constant message and fields. If the schema is unconfirmed, say so in the code (`SCHEMA_STATUS`), in the log and in the fixture's name.
3. **Fixture with provenance.** Put a real or clearly labelled sample under `fixtures/<source>/`, with `PROVENANCE.md` and `SHA256SUMS`, as `fixtures/omm/` and `fixtures/wayfinder/` do. Never present derived numbers as the source's data.
4. **Tests.** Add `tests/adapters/test_<source>.py`: one test per rejection code, a payload that becomes a `StateTable`, and a provenance check that the fixture's digest matches.
5. **Contract.** `ephemeris-and-adapters-are-independent` already covers `sentinel.adapters`: no risk, CDM codec, conjunction, sync, API or AI imports.

For a source of *conjunctions*, the seam is the CDM itself (ADR-001), specified in `docs/icd/cdm-profile.md`. A new admission code must be added there, or `tests/docs/test_cdm_profile.py` fails:
- if the source delivers CCSDS 508.0-B-1 KVN, no adapter code is needed: post the bytes to `POST /api/ingest/cdm`, or call `ConjunctionService.ingest`;
- if it delivers another shape, the adapter must produce a CDM. It needs `sentinel.cdm` to build and emit one, and `ephemeris-and-adapters-are-independent` forbids that inside `sentinel.adapters`. Give it its own package and contract, as `sentinel/screening` does for DERIVED CDMs, rather than weakening that contract.

Either way, never fill a field the source did not supply. A missing covariance stays missing, and the engine refuses the Pc.

### (d) An AI tool

1. **Catalog.** Add a `ToolInfo` to `TOOLS` in `sentinel/ai/catalog.py`: name, description, `needs_event`, `writes`. The description is the option text Jev chooses from, so its wording changes routing.
2. **Handler.** Add the handler to `_handlers` in `ToolRegistry` (`sentinel/ai/tools.py`). It returns facts: numbers taken from Sentinel's services, and dates and hours formatted by code (`_utc`, `_hours`). The `ai-does-no-math` contract forbids `sentinel.risk`, `sentinel.cdm`, numpy and scipy here, so a computation the services do not offer belongs in a service, not in the tool. A tool with `writes=True` returns a draft; only `Assistant.confirm` records anything.
3. **Template.** Add an entry to `TEMPLATES` in `sentinel/ai/narrate.py`. The template narrator is the floor and must cover every tool.
4. **Routing.** Add a slash command and, if it is natural to, keyword rules in `DeterministicRouter` (`sentinel/ai/router.py`). Jev sees the new tool automatically. If the tool needs an argument other than event, band, window or decision, add a Choice question in `_questions` and read it in `_to_route` in `sentinel/ai/router_jev.py`. Never ask Jev for a number: parse it from the text in code, as `window_hours` does.
5. **Grounding.** Every number the template or a model may state must be in the facts, at the precision stated, or in the question. Add the new tool's calls to `every_call` in `tests/ai/test_narrate.py`. That list is written by hand, so a new tool is not covered by `test_every_template_answer_passes_the_grounding_guard` until you add it.
6. **Eval.** Add at least six labelled requests for the tool to `evals/routing.jsonl`. `tests/ai/test_eval_set.py` fails until every tool in the catalog has six. Then regenerate the report, which CI requires to be current:

   ```bash
   make ai-eval
   ```

   The new eval set has a new hash, so any saved Jev run is reported as stale. Jev's column is filled only by a real run with `TYPESAFE_API_KEY` set; never by hand.
7. **Tests.** `tests/ai/test_tools.py` runs every catalogued tool automatically; add tests for the new tool's refusals (`ToolError` codes) and, for a writing tool, that nothing is recorded before confirmation.
8. **Trace.** Update the REQ-AI requirements' evidence in `mbse/verification.sysml` if the tool changes what they claim (recipe e).

### (e) A requirement and its evidence in `mbse/`

The requirement-to-evidence map lives in the SysML v2 model, not in pytest markers.

1. **Requirement.** Add `requirement <'REQ-<AREA>-NNN'> camelName { doc /* ... */ }` to `mbse/requirements.sysml`. Take every number in its criterion from a committed report or document. A new area also needs the `AREAS` set in `tests/mbse/test_real_model.py` and the area list at the top of `mbse/requirements.sysml`.
2. **Satisfaction.** Add `satisfy camelName by <part>;` to the satisfaction block of `mbse/sentinel.sysml`, naming the part that satisfies it.
3. **Verification.** Add a case to `mbse/verification.sysml`:

   ```
   verification <'VC-<AREA>-NNN'> vcCamelName : SentinelVerification {
       objective { verify camelName; }
       @VerificationMethod { kind = VerificationMethodKind::test; }
       @Evidence { kind = EvidenceKind::pytest; locator = "tests/<path>.py::test_<name>"; }
   }
   ```

   Evidence kinds: `pytest` (a node id in `pytest --collect-only -q`), `harness` (a scenario marked PASS in `docs/ddil-results.md`), `contract` (an id in `.importlinter`) and `ci` (a step name or job id in `.github/workflows/ci.yml`). If the evidence is not built yet, add `@Planned { milestone = "..."; reason = "..."; }`; the requirement then shows as unverified, never verified.
4. **Regenerate and check.**

   ```bash
   make trace          # rewrites docs/traceability.md; exits 1 on a broken reference
   make sysml-check    # SysML v2 grammar, in an isolated environment (PyPI the first time)
   uv run pytest -q tests/mbse
   ```

   `tests/mbse/test_real_model.py` fails when the committed trace is stale, when a reference is broken, when a requirement lacks a satisfying part or a case, and when an unverified requirement is not marked planned.

## Generated files

Never edit these by hand. Change the input and regenerate.

| File | Generated from | Regenerate with | Kept honest by |
|---|---|---|---|
| `docs/validation-report.md` | closed forms and NASA CARA's published values | `make report` | CI step "Validation report is reproducible" |
| `docs/ai-eval.md`, `docs/img/ai-reliability.svg` | `evals/routing.jsonl`, the routers | `make ai-eval` | CI step "AI eval report is reproducible (baseline; Jev needs a key CI never has)" |
| `docs/ddil-results.md` | `harness/results/*.json`, one per scenario; the report refuses to write with any missing | `make ddil` (GitHub download for the tools) | read by the trace as harness evidence; not re-run in CI |
| `docs/traceability.md` | `mbse/*.sysml`, pytest collection, `.importlinter`, `.github/workflows/ci.yml`, `docs/ddil-results.md` | `make trace` | `tests/mbse/test_real_model.py`; the CI `mbse` job |
| `docs/icd/openapi.json` | the FastAPI app's routes (`scripts/export_openapi.py`) | `make openapi` | `tests/docs/test_openapi_current.py`; CI step "ICDs are current (OpenAPI re-exported; bus, CDM and sync ICDs held to the code)" |
| `deploy/vex/sentinel.openvex.json` | `deploy/vex/statements.toml` and a raw Trivy scan | `make vex` (GitHub and Trivy's database) | `make scan`; the CI `supply-chain` job |
| `compliance/oscal/` profile, component definition, SSP and assessment plan | `compliance/sources/*.toml` | `uv run python scripts/oscal_evidence.py` | `tests/compliance/test_package_integrity.py` |
| `compliance/oscal/` assessment results and POA&M | a pytest JUnit run, harness results, an optional XCCDF scan | `make compliance` (PyPI for trestle) | `trestle validate -a`; the CI `compliance` job |
| `fixtures/cara_cases.json` | NASA CARA's spreadsheet and MATLAB unit tests in `fixtures/cara/` | `uv run --with openpyxl python scripts/transcribe_cara_fixtures.py` | tier 3 |
| `fixtures/wayfinder/ASSUMED-ephemeris-worldview3.json` and its `SHA256SUMS` | the public WORLDVIEW-3 element set, SGP4 | `make wayfinder-fixture` | `tests/adapters/test_wayfinder.py` re-derives every position |
| `fixtures/omm/celestrak-resource-20260924.json` | CelesTrak, on the day it was fetched | `uv run python scripts/fetch_omm.py resource` (network; writes a new dated file) | `fixtures/omm/SHA256SUMS`; refresh deliberately, never at test or run time |

For this guide, each command in the table was run and left its committed file unchanged, with these exceptions. `make compliance` and `scripts/oscal_evidence.py` were run on a scratch copy of the worktree, because a new run writes new assessment results by design; the four authored documents came out identical. `make ddil`, `make vex` and `scripts/fetch_omm.py` were not run, because they rewrite committed files from live measurements or live data.

Build output, all git-ignored: `web/dist/` (`make web`), `dist/` (bundles, SBOMs, scan results), `build/compliance/`, `.tools/`, `harness/results/`, and a node's `var/`. The screenshots in `docs/img/*.png` are captured by hand from a running node; no script regenerates them.

## Troubleshooting

### NATS defaults that assume a LAN

The DDIL harness found four `nats-server` defaults that fail over a satellite-class link. Each is fixed in `deploy/nats/hub.conf.tmpl` or `deploy/nats/edge.conf.tmpl`, guarded by a scenario, and pinned by `tests/compliance/test_deploy_conformance.py`. If you write your own NATS configuration, keep them:

| Default | What happened over the emulated link | Setting |
|---|---|---|
| The leaf listener advertises its URL | After the first disconnect, the edge reconnected directly to the advertised address, bypassing the intended path | `no_advertise: true` (hub) |
| Remote first-INFO timeout of 1 s | The hub's INFO takes longer than 1 s at 8 kbit/s plus 600 ms latency, so the leaf reconnected forever | `first_info_timeout: "20s"` (edge) |
| Leaf authentication timeout of 2 s | The handshake could not complete over the thin link | `authorization { timeout: 30 }` (hub) |
| Ping interval of 2 minutes | A black-holed link took minutes to detect | `ping_interval: "5s"`, `ping_max: 3` (both) |

The RECOVERY scenario (DENIED straight to LIMITED) failed until the second and third fixes were in (`docs/system-design.md`, "Findings from the DDIL harness"). The templates also set `write_deadline: "120s"`, so a slow link is not dropped as a slow consumer.

### Other symptoms

| Symptom | Likely cause | Where to look |
|---|---|---|
| Edge shows none of the hub's events, and the link as DENIED | No path to the hub: `SENTINEL_HUB_ID` unset, `SENTINEL_NATS_URL` unset (the in-process bus has no hub on it), or the leaf is down | `GET /api/sync`; the edge's NATS monitor at `/leafz`; the node log for `Waiting for nats-server` |
| Events stay HUB_ASSERTED | Summaries arrive but full CDMs do not: the link is too thin for them before their deadlines (`summary_only` in `GET /api/sync`), or fetches are failing | `queue`, `summary_only` and `last_cycle` in `GET /api/sync` |
| An event shows MISMATCH | The edge parsed the same CDM into different inputs than the hub did: its inputs hash differs from the one the hub asserted | `version` in `GET /api/node` on both nodes; `hash_ok` in the edge's `arrivals` (`GET /api/sync`) |
| Decisions from another node never appear | No `SENTINEL_TRUST_FILE`, so only the node's own entries merge | `rejected` in `GET /api/ops/digest` |
| Node fails under systemd with `Permission denied: 'var/keys'` | `SENTINEL_VAR` unset, so the node writes relative to `/` | `tests/test_deploy_env.py` |
| Console at `/` returns 404 | `web/dist` not built and `SENTINEL_WEB_DIST` unset | `make web` |
| Validation tab or library empty on an installed node | `SENTINEL_FIXTURES` not pointing at the bundle's `fixtures/` | log message `Reference library missing` |
| Assistant stays on the deterministic tier | Marking not UNCLASSIFIED, `SENTINEL_AI_CLOUD` not set, no key, the `ai` extra not installed, or the measured link | `reason` in `GET /api/ai/status`; log message `Hosted AI SDK not installed` |
| An AI answer was replaced by the template text | The grounding guard found a number the facts do not contain | `withheld.unsupported` in the answer |
| After a pull, collection fails with `ModuleNotFoundError` (for example `No module named 'yaml'`) | The dev extra gained a dependency your virtual environment predates | `uv pip install -e ".[dev]"` |
| A test fails with `SocketBlockedError` | The test tried to use the network | Use a fixture or a mock transport; `enable_socket` is only for loopback |
| `make trace` exits 1 | A verification case names evidence that does not exist | The "Problems" section the regenerated `docs/traceability.md` gains after its summary |
| `uv run lint-imports` reports a broken contract | An import crosses a module boundary | The contract named in the output; the table under [Architecture](#modules-and-their-allowed-dependencies) |
| `harness/cluster.py` exits with `missing: run make tools` | `nats-server` or `toxiproxy` not in `.tools/<arch>/` | `uv run python scripts/fetch_tools.py nats-server toxiproxy` |
| `python -m harness.report` prints `not writing ddil-results.md: no result for ...` | A scenario has no result in `harness/results/`, so the report would drop it | `make ddil` |
| The Passes tab lists every imager as skipped, or `GET /api/passes/catalog` is empty on an edge | Element sets have not arrived: the hub holds none (its log says `Element snapshot missing`) or lacks those imagers, or sync has not run yet | `GET /api/sync` on the edge; `SENTINEL_ELEMENTS` and `SENTINEL_SYNC_ELEMENTS` on the hub |
| `GET /api/passes` returns 409 or 503 | 409: no unit is set. 503: an element set for a catalogued imager cannot be propagated | `PUT /api/passes/unit`; the node log `Pass computation refused` |
| A node will not start: `SENTINEL_SYNC_ELEMENTS must be one of` | The value is not `catalog` or `all` | the configuration reference above |
| A node will not start: `SENTINEL_ROLE must be one of` | The value is not `hub`, `edge` or `standalone` | the configuration reference above |
| Requests reach a node you did not start | `make serve` and `make demo-local` use fixed ports 8000 and 8001; if another process holds them, your node fails to bind and your requests go to the other one | `node_id` and `role` in `GET /api/node`; `ss -ltn` |
| `make scan` fails on a commit that passed yesterday | Trivy's vulnerability database is not pinned, by design (RA-5) | `dist/scan/`; `docs/supply-chain.md` |
