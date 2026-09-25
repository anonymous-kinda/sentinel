# 3. CDMs, ingest and events

## What you will learn

- What a CCSDS Conjunction Data Message (CDM) holds, and how Sentinel reads and writes one without losing a keyword or a comment.
- The admission policy: input that would make an answer wrong is quarantined with a code; input that makes it incomplete is accepted with a warning.
- Every rejection code, including `IMPLAUSIBLE_STATE` and the physics behind its bounds.
- How CDMs become events: data class, event identity, the SQLite store and its version counter, and assessments cached per engine version.
- How an assessed event is banded for an operator, where the maneuver commit point comes from, and what the exercise scenario and the trajectory view are for.

## Why it exists

Chapter 2's engine takes one clean `Conjunction`. Real input is messier. Messages come from different providers, sometimes with a unit label that disagrees with the standard, sometimes without a covariance, sometimes simply wrong. A position written in metres under a `km` label would give a confident, wrong Pc. The engine cannot see that; the ingest layer has to.

Messages also come as a stream. The same close approach is reissued many times as tracking improves, so the operator thinks in *events*, not messages. They need the latest assessment of each event, its history, and an order: which event needs a decision first.

`sentinel/cdm/` and `sentinel/conjunction/` provide that. Every message is either admitted, with any limitation recorded beside it, or quarantined with a named reason. Admitted messages are grouped into events, stored as the exact bytes received, assessed, and banded against the operator's own thresholds and planning lead time. All of it runs on the node itself, so it keeps working when the link to any other node is down.

## Concepts

### The CDM

CCSDS 508.0-B-1 is the international standard for conjunction messages. Sentinel reads the Keyword = Value Notation (KVN) form. A message is a preamble followed by exactly two object blocks:

```
CCSDS_CDM_VERS    = 1.0                          header
CREATION_DATE     = 2008-06-25T21:10:11.000
ORIGINATOR        = JSPOC
MESSAGE_ID        = 28376_conj_01399_...
TCA               = 2008-06-27T15:34:55.320      relative metadata
MISS_DISTANCE     = 11.959493          [m]
RELATIVE_SPEED    = 14443.285750632    [m/s]
COMMENT HBR       = 20.0                         a convention, not a keyword
OBJECT            = OBJECT1                      object 1 (the primary)
OBJECT_DESIGNATOR = 28376
REF_FRAME         = EME2000
X                 = -1818.269382       [km]      state at TCA
...
Z_DOT             = 1.933211527        [km/s]
CR_R              = 1.858e+01          [m**2]    position covariance in the
CT_R ... CN_N                                    object's RTN frame (6 terms)
OBJECT            = OBJECT2                      object 2 (the secondary)
...
```

Three facts about the standard shape the code:

- **It has no event identifier.** Grouping updates into events is Sentinel's rule, so the rule is explicit.
- **It has no keyword for the hard-body radius.** NASA CARA and the 19th Space Defense Squadron carry it in a `COMMENT HBR = ...` line. Sentinel reads that convention.
- **Units are in the text.** Each value may carry a unit label in brackets. Positions are km, velocities km/s, covariances m². Chapter 2's engine converts to metres at its own boundary.

### Wrong versus incomplete

The admission policy is one rule, applied to every message from every source: *input that would make the answer wrong is quarantined; input that makes it incomplete is accepted with a warning; both are recorded.*

| Input | Class | What happens |
|---|---|---|
| A state labelled `[m]` instead of `[km]` | wrong | quarantined `WRONG_UNIT` |
| An Earth-fixed frame (ITRF) | wrong | quarantined `UNSUPPORTED_REF_FRAME`: converting it needs Earth-orientation data |
| Three covariance terms out of six | wrong | quarantined `PARTIAL_COVARIANCE`: completing it would invent data |
| A header miss distance that disagrees with the states | wrong | quarantined `MISS_DISTANCE_MISMATCH`: one of them is wrong |
| No covariance at all | incomplete | accepted, warning `COVARIANCE_ABSENT`; the engine refuses a Pc (`NO_COVARIANCE`) |
| An odd unit on a summary field the engine never reads | incomplete | accepted, warning `UNIT_LABEL_ANOMALY` |

The last row matters in practice: NASA's own Alfano sample CDMs label their relative velocities `[m]`. Discarding them would discard the benchmark cases. Sentinel recomputes relative velocity from the states, so the label cannot affect a result, and the anomaly is recorded, not punished.

A quarantined message never becomes an event. An admitted message can still be *refused a Pc* by the engine. A refusal is an assessment result with a `RefusalReason`, not an admission code.

### The rejection codes

| Code | Raised when |
|---|---|
| `PARSE_ERROR` | not structurally a KVN CDM: a bad line, not exactly two object blocks, objects out of order, no `CCSDS_CDM_VERS`, or a keyword twice in one block |
| `UNREADABLE` | a value cannot be read: a non-number, bytes that are not UTF-8, or a `COLLISION_PROBABILITY` that is NaN or infinite |
| `MISSING_TCA` | no `TCA` |
| `BAD_TCA` | `TCA` is not a CCSDS time, not a real date, or before 1957-10-04 (Sputnik 1) |
| `BAD_CREATION_DATE` | `CREATION_DATE` fails the same test |
| `MISSING_REF_FRAME` | an object has no `REF_FRAME` |
| `UNSUPPORTED_REF_FRAME` | the frame is not EME2000 or GCRF |
| `WRONG_UNIT` | a state or covariance term carries a unit label other than the required one |
| `MISSING_STATE` | an object lacks one of the six state components |
| `NONFINITE_STATE` | a state component is NaN or infinite |
| `IMPLAUSIBLE_STATE` | a state or covariance no Earth-orbiting object can have (below) |
| `PARTIAL_COVARIANCE` | some but not all six position covariance terms are present and finite |
| `MISS_DISTANCE_MISMATCH` | the header miss distance differs from the states' by more than max(2 m, 0.5 %) |

`docs/icd/cdm-profile.md` is the authoritative list, and `tests/docs/test_cdm_profile.py` holds it to the code in both directions.

### Physical bounds: `IMPLAUSIBLE_STATE`

Some states are not unusual but impossible, and the engine would still compute a Pc from them. The bounds are set from physics, generously, so no real CDM comes near them:

```
          admitted: 6,356.752 km  <=  |r|  <=  3,000,000 km
  |<- underground ->|<------------ orbits the Earth ------------>|<- rejected
  0            polar radius       Moon       L1/L2   halo orbits    3e6 km
                  (WGS-84)       ~0.4e6     ~1.5e6    to ~1.8e6

          admitted: |v| <= 100 km/s          each covariance term <= 9e18 m**2
```

- **Position.** The lower bound is the WGS-84 polar radius, the closest the surface comes to the Earth's centre; anything inside it is underground at every latitude. The upper bound is 3 million km, twice the distance to the Sun–Earth L1 and L2 points. Spacecraft on halo and Lissajous orbits there reach about 1.8 million km, beyond the Earth's Hill sphere (about 1.5 million km), so an upper bound at the Hill sphere would quarantine real CDMs for them. The bound still catches the most likely unit error: a low-orbit position written in metres under a `km` label reads as at least 6.36 million km.
- **Speed.** Every Earth orbit is slower than escape speed, 11.2 km/s at the surface. Nothing bound to the Sun passes the Earth faster than about 73 km/s. 100 km/s leaves margin for both.
- **Covariance.** A coordinate confined to ±R has a variance of at most R² (Popoviciu's inequality), and no covariance term exceeds the variances beside it. So no term can exceed (3 × 10⁹ m)² = 9 × 10¹⁸ m².

The state is checked once it is known to be finite, position before speed. The covariance is checked after the partial-covariance test.

### Data classes

Every CDM, and every event, is one of three classes:

- **REAL**: from an operational provider. A CDM posted to the API, or loaded from the NASA CARA reference library, is REAL unless marked otherwise.
- **DERIVED**: computed by Sentinel from public element sets in demonstration mode (chapter 10). No covariance, so never a Pc (ADR-002).
- **EXERCISE**: synthetic, for training and demonstration.

Sentinel's own generators mark their messages at the source with `ORIGINATOR = SENTINEL-EXERCISE` or `SENTINEL-SCREENING`. That mark decides the class whatever route the message arrived by, so exercise data cannot be passed off as REAL by posting it to the ingest endpoint.

### Events and identity

Two identities are at work:

- **Content identity.** The SHA-256 of the bytes as received. The same bytes twice are a no-op (`duplicate`). The same message with its columns realigned is different bytes, so a different CDM.
- **Event identity.** A CDM joins an existing event when it names the same *ordered* pair of object designators, has the same data class, and its TCA is within 60 s of the event's reference TCA, the TCA of the event's first CDM. Otherwise it starts a new event with the id `<OBJECT1>-<OBJECT2>-<TCA as YYYYMMDDThhmmss>`, for example `28376-1399-20080627T153455`.

```
  CDM arrives ──► same pair, same class, |TCA − reference TCA| ≤ 60 s ?
                        │ yes                          │ no
                        ▼                              ▼
                 join that event               new event, id from pair + TCA
                                               (+ "-<CLASS>" if another class
                                                already holds that id)
```

The id is assigned once, on the node where the CDM is first ingested, and travels with the record. An edge node takes the hub's id as given (chapter 7). If each node re-derived it, updates fetched out of order could split one event into two.

Within an event, the *latest* CDM is the one with the latest `CREATION_DATE`, then the latest arrival. The event's band comes from the latest CDM's assessment. A late-arriving old message does not replace a newer one.

### Triage: bands, worst case and the maneuver commit point

The engine's result is reduced to what an operator scans first. The defaults in `ConjunctionPolicy` are operator assumptions, not physics, and the console labels them as such:

| Band | When |
|---|---|
| RED | Pc ≥ 1e-4, the maneuver-planning threshold in NASA CARA's published practice |
| AMBER | Pc ≥ 1e-5 |
| GREEN | below |
| UNASSESSED | the engine refused |

A diluted result also carries a **worst-case band**, the band its `pc_max` would have. The worst case raises attention, never action on its own. The consequence level combines them:

- **CRITICAL**: the band is RED.
- **SERIOUS**: the band is AMBER, or the worst case is RED.
- **WATCH**: the band is UNASSESSED, or the worst case is AMBER.
- **ROUTINE**: everything else.

`needs_attention` is true from SERIOUS up. An UNASSESSED event is WATCH, not ROUTINE: no number is not the same as a safe number.

The **maneuver commit point (MCP)** is the last moment a decision still helps. It is the TCA minus the time an operator needs to plan, approve, uplink and execute a burn, 8 hours by default:

```
   now ──────────────── MCP = TCA − 8 h ──────────────── TCA
        decide before here       too late to plan, approve,
                                 uplink and execute a burn
```

Active events are listed soonest MCP first, then worst consequence. The same MCP is the deadline the sync layer orders by on a thin link (ADR-006, chapter 7).

## Code walkthrough

Read `sentinel/cdm/` first, which knows nothing of events or nodes, then `sentinel/conjunction/`.

### `sentinel/cdm/model.py`

The in-memory CDM. `CdmMessage` holds a `preamble` and two `objects`, each a `CdmSection` of ordered entries: `KvnField(key, value, unit)` or `Comment(text)`. Values stay as the text received; typed accessors convert on read (`CdmSection.number`, `CdmMessage.tca`, `CdmMessage.miss_distance_m`). `hbr_from_comment_m` reads the `COMMENT HBR = ...` convention and accepts only metres, explicit or unlabelled; any other label is ignored rather than guessed at. `collision_probability` is the *originator's* Pc, and its docstring says it is never Sentinel's.

*Easy to get wrong:* the model is deliberately stringly typed. Converting everything to floats on parse would lose the original text and unit labels, and with them the round trip.

### `sentinel/cdm/kvn.py`

`parse` and `parse_bytes` turn text into a `CdmMessage`; `emit` turns it back. Parsing is structural only: `OBJECT = OBJECT1` then `OBJECT2`, exactly two blocks, `CCSDS_CDM_VERS` present, and no keyword twice in one block. Two values for one keyword raise `CdmParseError`, because keeping either one would be a guess. `emit` realigns the columns, and `parse(emit(m)) == m` for every keyword, unit and comment (`tests/test_cdm_codec.py` checks every NASA file).

*Easy to get wrong:* do not add physical checks here. A readable-but-wrong message must parse, so that `validate.py` can quarantine it with a precise code instead of a generic parse error.

### `sentinel/cdm/timefmt.py`

`parse_ccsds_time` accepts both CCSDS calendar forms, `YYYY-MM-DDThh:mm:ss` and day-of-year `YYYY-DDDThh:mm:ss`, because NASA's own files use both. Times are UTC. Digits beyond the microsecond are truncated.

### `sentinel/cdm/validate.py`

The admission policy. `validate(message)` raises `CdmRejected(code, detail, object_index)` for wrong input and returns a list of `CdmWarning` for incomplete input. The order is: TCA, creation date and the originator's Pc; summary-field unit labels (warnings); then for each object its frame, its unit labels, its state (`_state_vector`, `_check_plausible_state`) and its covariance (`covariance_status`, `_check_plausible_covariance`); and last, the header miss distance against the states. The bounds are module constants: `WGS84_POLAR_RADIUS_KM`, `MAX_RADIUS_KM`, `MAX_SPEED_KM_S`, `MAX_POSITION_VARIANCE_M2`, `EARLIEST_TCA`.

*Easy to get wrong:* an absent unit label is accepted as the standard's default; only a present, different label is rejected. And a NaN covariance term counts as absent: all six NaN means no covariance (a warning), while some NaN and some finite means `PARTIAL_COVARIANCE`.

### `sentinel/cdm/to_conjunction.py`

The one place that knows both the CDM's vocabulary and the engine's. `to_conjunction(message, hbr_override_m)` validates, then builds the `Conjunction` and returns a `Conversion(conjunction, hbr_source, warnings)`. The covariance's six lower-triangle terms become a symmetric 3×3 matrix. `resolve_radii` chooses the radius, in order:

1. an explicit override (`sentinel assess --hbr`), split evenly;
2. a combined `COMMENT HBR`, split evenly (only the sum enters the 2D integral);
3. each object's `AREA_PC`, as `sqrt(A/π)`, only if both objects give one;
4. none: the radii stay `None` and the engine refuses `NO_HBR`.

`hbr_source` records which one was used.

*Easy to get wrong:* no radius is ever invented here. A default radius is an engine configuration choice (`AssessmentConfig.default_radius_m`), recorded as `hbr_defaulted`, and a node sets none.

### `sentinel/cdm/admission.py`

The one path from raw bytes to a validated `Conjunction`. The node's ingest and the CLI both take it, so they cannot disagree about a message. `admit(raw, hbr_override_m)` returns `Admitted(message, conversion)` or raises `CdmRejected` with the code the node quarantines under. `read_message` turns bytes that are not UTF-8 into `UNREADABLE` and a `CdmParseError` into `PARSE_ERROR`. Any other `ValueError` or `KeyError` during conversion also becomes `UNREADABLE`, for example a `COMMENT HBR = 1.2.3` or an `AREA_PC = abc`, and the reason names the value. `sentinel cdm emit` needs only the structure, so it calls `read_message` alone.

*Easy to get wrong:* reading a CDM with `parse_bytes` and `to_conjunction` directly. An unreadable value then escapes as a plain `ValueError`, and the caller must classify it itself or end in a traceback. Where an answer reaches a user, go through `admit`.

### `sentinel/conjunction/store.py`

`ConjunctionStore` is a SQLite projection. The raw CDM bytes are the source of truth; the tables are `cdm_messages`, `events`, `assessments` (keyed by sha256 and engine version), `remote_summaries` (what a hub asserted, chapter 7) and `quarantine`. A lock serialises access. CDMs, events and quarantine rows are inserted with `INSERT OR IGNORE`, so a repeat is harmless; assessments and hub summaries are replaced. `cdms_for_event` orders by `CREATION_DATE`, then arrival, which is how "latest" is defined.

`version` counts changes to stored CDMs, events and hub summaries. It changes exactly when a view built from them can, so a view can be cached against it: the manifest a hub offers its edges is rebuilt only when `version` moves. Assessments do not bump it, because each is a pure function of one stored CDM under one engine version. `has_cdm_prefix` and `cdm_by_prefix` find a record by the leading hex digits of its hash with a range query on the primary key, which the sync layer uses.

*Easy to get wrong:* `version` lives in memory and restarts at zero with the process. It is a cache key for this process, not a persistent revision number.

### `sentinel/conjunction/service.py`

`ConjunctionService` ties it together. `ingest(raw, source, data_class, event_id)` is the only way in, and every route calls it (the table at the top of `docs/icd/cdm-profile.md`):

```
raw bytes ─ sha256 already stored? ── yes ──► duplicate (no-op)
          ─ admit (sentinel/cdm/admission.py)
                CdmRejected ────────────────► quarantine with its code:
                                              PARSE_ERROR, UNREADABLE or the validator's
          ─ ORIGINATOR mark ────────────────► data class
          ─ _event_for ─────────────────────► event (joined or new)
          ─ store.add_cdm (raw bytes kept)
          ─ _assess_sha ────────────────────► assessment, cached
          ─ publish node.<id>.cdm.accepted.<event_id>
```

`_reject` writes the quarantine row, logs the warning `CDM quarantined` with the code, sha256 and source (never the content, which the detail can quote), and publishes `node.<id>.cdm.rejected`. `_event_for` implements the identity rule; when `event_id` is passed (an edge fetching from its hub), it takes that id without re-deriving it. `_new_event_id` appends the data class when another class already holds the plain id.

`_assess_sha` looks up the stored assessment for `(sha256, engine_version)` and computes it only on a miss. `engine_version` is `sentinel.__version__` plus a 12-character hash of the `AssessmentConfig`, so changing a threshold re-assesses every CDM from its raw bytes the next time it is viewed. `_parsed` keeps recently parsed messages in a bounded cache.

The views are computed on request, not at ingest:

- `event_summary`: the latest CDM's assessment, triaged, with MCP, band, worst case, consequence and the originator's Pc beside Sentinel's.
- `list_events(scope)`: active, past or all, sorted by triage order. On an edge it also lists events known only from the hub's summaries.
- `event_detail`: the summary plus every CDM's own assessment and warnings, and the engine version and policy that produced them.
- `encounter`, `dilution_curve` and `trajectory`: the console's plots (chapter 5). `dilution_curve` integrates with the engine configuration's panel cap (`quadrature_panels_cap`), so its curve agrees with the assessment beside it under any configuration.
- `knows`: whether the node has heard of an event at all, from its own CDMs or from a hub's summary. The API answers 404 for an event it does not know, and `available: false` for a known one without the data.
- `manifest`: the compact summaries a hub offers edges, cached against `store.version` (chapter 7).

*Easy to get wrong:* the assessment cache trusts the engine version. With a persistent database (`SENTINEL_DB` set to a file), a change to `sentinel/risk/` that keeps both the version and the configuration serves the old cached results. A release that changes the engine must bump `sentinel.__version__`.

### `sentinel/conjunction/policy.py`

`ConjunctionPolicy` holds the operator's assumptions: `red_pc`, `amber_pc`, `mcp_lead_time_s` and `urgent_window_s`. `band_for` maps a Pc to a `Band`, and `triage(result, tca, policy)` returns a `Triage` with band, worst-case band, consequence, MCP and `needs_attention`, by the rules under Concepts. `triage_key` is the only thing the sync layer learns about a conjunction: an event id, a priority class, a deadline (the MCP) and a consequence. A full record is urgent when its consequence is SERIOUS or worse and its MCP is within `urgent_window_s` (72 h).

*Easy to get wrong:* a refused result is banded from `pc = None`, never from a number. `triage` checks `result.method` before it reads `pc`.

### `sentinel/conjunction/exercise.py`

The exercise scenario: eight scripted events (`SCENARIO`), each a sequence of CDM updates timed relative to an epoch. Each event demonstrates one behaviour:

| Script | Demonstrates |
|---|---|
| `EX-DIL` | covariance inflates; Pc rises, peaks and falls while the dilution flag lights |
| `EX-RED` | a close approach whose covariance tightens; RED throughout |
| `EX-AMB`, `EX-GRN` | steady AMBER and routine GREEN |
| `EX-GEO` | GEO co-location at 0.3 m/s: refused `LOW_RELATIVE_VELOCITY` |
| `EX-NOCOV` | secondary without covariance: admitted with a warning, refused `NO_COVARIANCE` |
| `EX-BAN` | 300 km along-track sigma: refused `CURVILINEAR_UNCERTAINTY` |
| `EX-NPD` | a correlation above 1, so not a covariance: refused `INVALID_COVARIANCE` |

`build_message` builds circular-orbit states with the requested miss vector in the encounter plane, an RTN covariance with a typical radial/along-track correlation, and `COMMENT HBR = 20 [m]`. Every message is labelled at the source: `ORIGINATOR = SENTINEL-EXERCISE`, a comment line saying it is not a real conjunction, designators in the 99xxx range and names ending `(EXERCISE)`. `generate(epoch)` returns the whole scenario sorted by release time. Every time a message carries is UTC, its `MESSAGE_ID` and so its file name included, whatever timezone the epoch is written in; a naive epoch is refused rather than read as the host's local time. A node's exercise feeder ingests each message when its clock reaches the release time, so updates dated after start-up arrive while you watch.

*Easy to get wrong:* the scenario is a demonstration, not a validation. Its numbers are whatever the engine computes from synthetic geometry; the engine's correctness comes from chapter 2's CARA comparison.

### `sentinel/conjunction/trajectory.py`

`encounter_arcs_ecef(conjunction, tca)` draws the two objects' orbits for ±20 minutes around TCA on the console's globe. It propagates each state with two-body gravity (SciPy's `solve_ivp`) and rotates to an Earth-fixed frame by Greenwich mean sidereal time alone. That is kilometre-class accurate: fine for a picture, never used for a number. It draws only from a state inside the same radius band ingest admits (it imports the bounds from `sentinel/cdm/validate.py`), and it raises `TrajectoryUnavailable` otherwise, which the API returns as 422.

The remaining files, `summaries.py` and `sync_adapter.py`, are the conjunction module's side of the sync interface; chapter 7 covers them.

## Try it

Run from the repository root. Keep a scratch directory for the files you make:

```bash
export SCRATCH=$(mktemp -d)
```

**1. Read a CDM with the codec.**

```bash
uv run sentinel cdm parse fixtures/cara/SampleCDMs/AlfanoTestCase01.cdm
uv run sentinel cdm emit fixtures/cara/SampleCDMs/AlfanoTestCase01.cdm > $SCRATCH/alfano.cdm
uv run sentinel cdm emit $SCRATCH/alfano.cdm | diff $SCRATCH/alfano.cdm - && echo "round trip: same"
```

`cdm parse` prints the message id, the two designators, `hbr_from_comment_m` (15 m, read from the comment) and three `UNIT_LABEL_ANOMALY` warnings for NASA's `[m]` labels on relative velocity. The message is admitted. The second emit reproduces the first exactly, but the first differs from NASA's file in its column widths: same message, different bytes, so a different SHA-256.

**2. Quarantine a wrong message.** Write one object's Z coordinate in metres under the `km` label, and change a frame:

```bash
sed 's/-6772.707308/-6772707.308/' fixtures/cara/SampleCDMs/OmitronTestCase_Test01_HighPc.cdm > $SCRATCH/metres.cdm
uv run sentinel cdm parse $SCRATCH/metres.cdm; echo "exit $?"
sed 's/EME2000/ITRF/' fixtures/cara/SampleCDMs/OmitronTestCase_Test01_HighPc.cdm > $SCRATCH/itrf.cdm
uv run sentinel cdm parse $SCRATCH/itrf.cdm; echo "exit $?"
```

Both print `REJECTED` with a code, the object and the detail on standard error, and exit 2. The first reads |r| ≈ 6.8 million km, beyond the 3 million km bound: `IMPLAUSIBLE_STATE (OBJECT1)`. The second is `UNSUPPORTED_REF_FRAME (OBJECT1)`.

**3. Start a node of your own.** The live demonstration uses ports 8000 and 8001, so use another port:

```bash
SENTINEL_VAR=$SCRATCH uv run sentinel serve --port 8765 > $SCRATCH/node.log 2>&1 &
curl -s http://127.0.0.1:8765/api/health
```

Retry the health check until it answers. The log shows the reference library loading: NASA's operational CDMs, ingested as REAL events through the same `ingest` call. The database is in memory, so stopping the node discards everything.

**4. Admit, repeat and reject over HTTP.** Use NASA's Omitron sample `fixtures/cara/SampleCDMs/OmitronTestCase_Test01_HighPc.cdm`, which the library does not load:

```bash
curl -s -w '\nHTTP %{http_code}\n' --data-binary @fixtures/cara/SampleCDMs/OmitronTestCase_Test01_HighPc.cdm http://127.0.0.1:8765/api/ingest/cdm
curl -s -w '\nHTTP %{http_code}\n' --data-binary @fixtures/cara/SampleCDMs/OmitronTestCase_Test01_HighPc.cdm http://127.0.0.1:8765/api/ingest/cdm
curl -s -w '\nHTTP %{http_code}\n' --data-binary @$SCRATCH/metres.cdm http://127.0.0.1:8765/api/ingest/cdm
curl -s http://127.0.0.1:8765/api/quarantine
```

- The first answers **201**, `accepted`, with `event_id` `28376-1399-20080627T153455` and the three unit-label warnings.
- The second answers **200**, `duplicate`, with the same sha256. Nothing else happened.
- The third answers **422**, `rejected`, `IMPLAUSIBLE_STATE`, and the quarantine list now holds it with its source, `api-upload`.

**5. Read the event, then supersede it.**

```bash
curl -s http://127.0.0.1:8765/api/events/28376-1399-20080627T153455 | python3 -m json.tool
sed '/^COMMENT HBR/d' fixtures/cara/SampleCDMs/OmitronTestCase_Test01_HighPc.cdm > $SCRATCH/no-hbr.cdm
curl -s -w '\nHTTP %{http_code}\n' --data-binary @$SCRATCH/no-hbr.cdm http://127.0.0.1:8765/api/ingest/cdm
curl -s http://127.0.0.1:8765/api/events/28376-1399-20080627T153455 | python3 -m json.tool | grep -E '"(band|worst_case_band|consequence|cdm_count|refusal_reason|hbr_source)"'
```

The first read shows `summary` (data class REAL, the MCP 8 h before TCA, band RED, a worst-case band because the result is diluted, consequence CRITICAL), a `history` of one CDM with its own assessment and warnings, the `engine_version` and the `policy`. Then post the same message without its HBR comment. It is new bytes, so it is accepted, and it joins the same event: same pair, same class, same TCA. It has the same `CREATION_DATE`, so the later arrival becomes the latest CDM. The event is now `UNASSESSED` and WATCH, and `cdm_count` is 2. The history keeps both: the first with `hbr_source` `cdm_comment_hbr` and a Pc, the second with no HBR and `NO_HBR`.

**6. Watch the exercise events.**

```bash
curl -s http://127.0.0.1:8765/api/events | python3 -m json.tool | grep -E '"(event_id|band|worst_case_band|refusal_reason)"'
curl -s http://127.0.0.1:8765/api/node | python3 -m json.tool | grep -E '"(engine_version|red_pc|amber_pc|mcp_lead_time_s)"'
```

Active events are only the exercise ones: every NASA event's TCA is in the past. They are sorted soonest MCP first, and the refused ones show their reason with band `UNASSESSED`. Find the `99001-99412-...` event (EX-DIL). Its id ends in the node's start time plus 30 h. Four minutes after start-up, list again: its last two updates have been released, and it has moved from RED to AMBER with a worst-case band of RED. The covariance grew, the Pc fell, and the flag says why. `GET /api/node` shows the engine version and the policy the bands came from.

**7. Draw the trajectory, then stop the node.**

```bash
curl -s http://127.0.0.1:8765/api/events/28376-1399-20080627T153455/trajectory | head -c 300; echo
kill %1
```

The reply starts with the TCA, the note `two-body arcs, visualization only`, and samples of `[offset_s, x, y, z]` in Earth-fixed metres.

**8. Generate the exercise scenario as files.**

```bash
uv run sentinel exercise generate --out $SCRATCH/ex --epoch 2026-09-24T12:00:00+00:00
ls $SCRATCH/ex
uv run sentinel assess $SCRATCH/ex/EX-GEO-01-20260924T020000.cdm
uv run sentinel assess $SCRATCH/ex/EX-DIL-05-20260924T120336.cdm
```

Sixteen files, named by script, update number and UTC creation time. An `--epoch` without a timezone is read as UTC, as `sentinel screen` reads `--start`, so `--epoch 2026-09-24T12:00:00` writes the same files. Open any file: `ORIGINATOR = SENTINEL-EXERCISE` and the EXERCISE comment are in the header. EX-GEO is refused for its 0.3 m/s relative speed. EX-DIL's last update prints `DILUTED` with `k*` well below 1.

**9. Run the rungs that hold this chapter's code.**

```bash
uv run pytest -q tests/test_cdm_codec.py tests/test_ingest_hostile.py tests/conjunction tests/docs/test_cdm_profile.py
```

`tests/test_ingest_hostile.py` feeds a catalogue of hostile KVN variants and asserts that each is admitted or quarantined, and that every view still serves afterwards. `tests/conjunction/test_event_grouping.py` pins the data-class rule, and `tests/conjunction/test_manifest_cache.py` pins the version-counter cache.

## Design choices

**The CDM is the contract** ([ADR-001](../system-design.md#adr-001--cdm-as-the-canonical-internal-data-contract)).
- *Buys:* no tie to one provider. A new source is one adapter that emits a CDM, and nothing downstream knows where data came from. The model keeps every keyword, unit and comment, so a message forwarded across a link is the message that arrived.
- *Costs:* whatever a source knows beyond the CDM's fields stops at the seam, and Sentinel maintains its own codec.
- *Rejected:* a bespoke JSON schema (simpler, and worthless as an open interface), and passing raw provider payloads through (every module coupled to every source).

**Wrong raises, incomplete degrades, both are recorded.**
- *Buys:* a wrong message cannot produce a confident number, and an imperfect but usable one still reaches the operator with its limitation attached. Nothing is dropped silently: every rejection has a row, a code and a bus event.
- *Costs:* a strict reader turns some messages away that a lenient one would use, for example an ITRF state that could be converted with Earth-orientation data.
- *Rejected:* rejecting every imperfection, which would turn away NASA's own sample files; repairing input (completing a partial covariance, converting a mislabelled unit), which invents data and hides the fault.

**Physical bounds from physics, set wide.** The bounds catch the impossible and the classic unit slip, and no real CDM is near them. They do not catch a plausible but wrong state; that is not their job, and nothing at ingest could. The upper radius was first the Hill sphere and was raised to 3 million km when that bound turned out to quarantine real libration-point spacecraft.

**Identity assigned once and carried** ([ADR-008](../system-design.md#adr-008--reference-data-application-level-priority-pull-not-transport-replication)). Re-deriving the event id on each node would let out-of-order arrivals split one event in two. The cost is that an edge trusts the hub's grouping without re-checking it. One data class per event keeps a DERIVED screening CDM's `NO_COVARIANCE` refusal from becoming the latest word on a REAL event with a real Pc.

**Raw bytes are the truth; results are derived and cached per engine version.**
- *Buys:* any number can be recomputed from the bytes that produced it, the hub can serve an edge the identical bytes it received, and a threshold change re-assesses everything.
- *Costs:* results are recomputed on a cache miss, and the cache is only as honest as the version string.
- *Rejected:* storing only parsed values or results, which could not be re-verified or forwarded unchanged.

**Triage by decision urgency** ([ADR-006](../system-design.md#adr-006--bandwidth-triage-by-decision-urgency)). Bands and the MCP are operator assumptions in one policy object, shown with every event. One MCP lead time applies to every asset, which real operations would set per asset. The worst case drives attention, never action.

**Exercise data labelled at the source.** A mark inside the message survives every route, file copy and sync hop. A route-level flag would not.

## How it fails

- **Unreadable or wrong input** is quarantined, never assessed. The node answers 422 with the code, stores the bytes, code, detail and source in `quarantine` (`GET /api/quarantine`), publishes `cdm.rejected`, which the console receives on its live stream, and logs the warning `CDM quarantined` with the code, sha256 and source.
- **Incomplete input** is accepted, with its warnings returned by the ingest call and stored with the CDM (`history[].warnings`).
- **A refused assessment** is still an event. Its band is UNASSESSED and its consequence WATCH, so it asks for attention rather than looking safe.
- **Repeats** are free: the same bytes are a 200 no-op. A body over 1 MB is refused with 413; the node stops reading at the limit.
- **A state the globe cannot draw** returns 422 from the trajectory route; the event and its assessment are unaffected.
- **A denied link** does not stop ingest or assessment: both are local. What crosses a link is chapter 7.
- **The CLI judges a file as the node would.** `sentinel assess` and `sentinel cdm parse` read it through the same `admit`, so whatever the node would quarantine, a parse error included, prints `REJECTED` with the node's code and reason on standard error and exits 2, never with a traceback.
- **A known gap.** At the time of writing, a CDM in which one object's velocity is zero, or exactly parallel to its position, passes admission and then makes the engine raise (chapter 2, "How it fails"). The node stores the CDM before assessing it, so the ingest request fails with HTTP 500, and every later `GET /api/events` fails too, because listing events assesses each one. The catalogue in `tests/test_ingest_hostile.py` has no such variant yet. A fix needs one there, and a gate in `sentinel/risk/engine.py` or a bound in `sentinel/cdm/validate.py`.

## Check yourself

1. A CDM arrives with `X`, `Y` and `Z` labelled `[m]` and values that look like metres. Why does Sentinel quarantine it instead of dividing by 1000?
   <details><summary>Answer</summary>A label that disagrees with the standard means the producer's pipeline did something unexpected, and Sentinel cannot tell whether the label or the numbers are wrong. Converting assumes the numbers match the label; if they do not, the result is a confident, wrong Pc. Quarantining with <code>WRONG_UNIT</code> keeps the message and the reason for a human to resolve. A summary field with an odd label is different: the engine never reads its value, so the anomaly is only recorded.</details>

2. A provider re-sends a CDM after a tool has realigned its columns. What does the node do, and does the event change?
   <details><summary>Answer</summary>The bytes differ, so the SHA-256 differs and it is not a duplicate: it is admitted as a new CDM. It names the same pair, class and TCA, so it joins the same event and <code>cdm_count</code> goes up. Its parsed content is identical, so its assessment is the same. With equal <code>CREATION_DATE</code>s, the later arrival becomes the latest CDM.</details>

3. Three REAL CDMs for one pair have TCAs of T, T + 45 s and T + 90 s, arriving in that order. How many events result, and why?
   <details><summary>Answer</summary>Two. The rule compares each CDM's TCA with the event's reference TCA, the TCA of its first CDM, not with the latest. T + 45 s is within 60 s of T and joins; T + 90 s is 90 s from T and starts a new event, even though it is only 45 s from the previous update.</details>

4. A screening run produces a DERIVED CDM for the same pair and TCA second as an existing REAL event. What id does its event get, and what would go wrong if it joined the REAL event?
   <details><summary>Answer</summary>It starts its own event, <code>&lt;pair&gt;-&lt;TCA&gt;-DERIVED</code>, because the plain id is taken by an event of another class. If it joined, it could become the REAL event's latest CDM, and its <code>NO_COVARIANCE</code> refusal would replace a real Pc with UNASSESSED.</details>

5. An event's latest assessment has Pc = 3e-5, is diluted, and has <code>pc_max</code> = 2e-4. Give its band, worst-case band, consequence and <code>needs_attention</code> under the default policy.
   <details><summary>Answer</summary>Band AMBER (at least 1e-5, below 1e-4); worst-case band RED (2e-4 is at least 1e-4); consequence SERIOUS, because the worst case is RED; <code>needs_attention</code> true. The Pc alone says AMBER, but the worst case says an operator should look.</details>

6. You raise <code>max_curvilinear_ratio</code> on a node with a file database and restart it. Do old events show new results? What if instead you fix a bug in <code>sentinel/risk/integrate.py</code> and restart?
   <details><summary>Answer</summary>The threshold change: yes. <code>engine_version</code> includes a hash of the configuration, the cached rows no longer match, and each CDM is re-assessed from its raw bytes when viewed. The code fix: no, unless <code>sentinel.__version__</code> also changes. The version string and configuration are the same, so the old cached results are served.</details>

7. Why is the upper position bound 3 million km rather than the Earth's Hill sphere, and why does a unit error still fail it?
   <details><summary>Answer</summary>Spacecraft on halo orbits around the Sun–Earth L1 and L2 points reach about 1.8 million km, outside the Hill sphere (about 1.5 million km), so a Hill-sphere bound would quarantine real CDMs. 3 million km is twice the L1/L2 distance. A low-orbit position written in metres under a <code>km</code> label reads as at least 6.36 million km, still more than twice the bound.</details>

8. The hub and an edge each ingest the same CDM, but the edge fetched the event's second update before its first. Why must the edge not group CDMs itself?
   <details><summary>Answer</summary>Grouping depends on the event's reference TCA, which is the TCA of its first CDM. If the edge saw a later update first, its reference TCA would differ, and a CDM that joins the hub's event could start a new one on the edge. The id is assigned once, on the hub, and travels with each record (<code>Sentinel-Event-Id</code>), so both nodes agree whatever the arrival order.</details>

## Where next

- [Chapter 4: The node and its API](04-node-and-api.md): the routes used above, the start-up sequence and the settings.
- [Chapter 5: The operator console](05-console.md): how bands, the worst case, refusals and the trajectory are shown.
- [Chapter 7: Priority sync](07-priority-sync.md): the compact summaries, the manifest cached against `store.version`, and how an edge verifies a hub's assessment.
- [Chapter 10: Passes and screening](10-passes-and-screening.md): where DERIVED CDMs come from.
- `docs/icd/cdm-profile.md`: the admission profile, every keyword rule and code, the physical bounds and the identity rules.
- [ADR-001](../system-design.md#adr-001--cdm-as-the-canonical-internal-data-contract), [ADR-006](../system-design.md#adr-006--bandwidth-triage-by-decision-urgency) and [ADR-008](../system-design.md#adr-008--reference-data-application-level-priority-pull-not-transport-replication) in `docs/system-design.md`.
