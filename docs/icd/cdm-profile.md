# Interface control: CDM admission profile

Sentinel's profile of the CCSDS 508.0-B-1 Conjunction Data Message (Blue
Book, June 2013). It covers which keywords Sentinel requires, checks, uses,
or carries without using. It also sets the admission policy at the ADR-001
seam: every CDM passes through it, from any source, before anything
downstream sees it.

Every route in goes through one function, `ConjunctionService.ingest`
(`sentinel/conjunction/service.py`):

| Route | Source recorded | Data class unless ORIGINATOR marks it |
|---|---|---|
| `POST /api/ingest/cdm` (`docs/icd/openapi.json`) | `api-upload` | `REAL` |
| NASA CARA reference library, loaded at start | `nasa-cara-library` | `REAL` |
| Exercise feeder | `exercise-feed` | `EXERCISE` |
| Sync fetch from the hub (`docs/icd/sync-envelope.md`) | `sync:<hub_id>` | the hub's `Sentinel-Data-Class` header |

The policy is the ARMOR rule. Input that would make an answer **wrong** is
quarantined with a code. Input that makes it **incomplete** is accepted with
a warning. Both are recorded; neither is swallowed.

`tests/docs/test_cdm_profile.py` holds this document to the code. Every
rejection and warning code, accepted frame, unit rule and data-class mark
below is read from the source and compared both ways.

## Encoding

- **KVN only.** One message per request, UTF-8 or ASCII, with an optional
  byte-order mark. At most 1 MB over HTTP (413 above that). An XML CDM is not
  KVN and is rejected with `PARSE_ERROR`.
- **Structure.** A preamble (header and relative metadata), then exactly two
  object blocks, opened by `OBJECT = OBJECT1` and `OBJECT = OBJECT2` in that
  order.
- **Keywords.** Each line is `KEY = VALUE [unit]`. `COMMENT` lines may appear
  anywhere and are kept verbatim, in place.
- **Times.** CCSDS 301.0-B-4 ASCII time code A (`YYYY-MM-DDThh:mm:ss.d`) or
  B (`YYYY-DDDThh:mm:ss.d`), UTC, with an optional trailing `Z`. Digits
  beyond the microsecond are truncated. NASA CARA's own files use both
  forms.

## Admission sequence

```
bytes --sha256--> seen before?          -> duplicate: no-op (HTTP 200)
      --parse---> not a KVN CDM?        -> quarantine PARSE_ERROR
      --read----> value not readable?   -> quarantine UNREADABLE
      --validate> wrong?                -> quarantine with the code
      --mark----> data class (ORIGINATOR mark wins)
      --group---> event identity
      --store---> raw bytes kept as received
      --assess--> Pc or a refusal (a refusal is a result, not an error)
      --publish-> node.<node_id>.cdm.accepted.<event_id>   (HTTP 201)
```

A quarantined message is stored with its sha256, code, detail and source.
It is listed by `GET /api/quarantine` and published on
`node.<node_id>.cdm.rejected` (`docs/icd/asyncapi.yaml`). Over HTTP it is
answered with 422 and the code. It never becomes an event.

## Keywords

**Required.** A message without these is rejected.

| Keyword | Block | Rule |
|---|---|---|
| `CCSDS_CDM_VERS` | header | Must be present. The value is not checked. |
| `TCA` | relative metadata | Must be present and a CCSDS time. |
| `OBJECT` | each object | `OBJECT1`, then `OBJECT2`, exactly two blocks. |
| `REF_FRAME` | each object | One of the accepted frames (below). |
| `X` `Y` `Z` `X_DOT` `Y_DOT` `Z_DOT` | each object | Present, finite, and in the required units. |

**Checked when present.**

| Keyword | Rule |
|---|---|
| `CREATION_DATE` | Must be a CCSDS time. It also stamps the record's creation time in the sync manifest; without it, the time of receipt is used. |
| `CR_R` `CT_R` `CT_T` `CN_R` `CN_T` `CN_N` | Position covariance in the object's RTN frame. All six finite, or none: a partial covariance is rejected rather than completed by invention. None is accepted with a warning, and the engine then refuses a Pc (`NO_COVARIANCE`). A `NaN` counts as absent. |
| `MISS_DISTANCE` | Cross-checked against the states. A disagreement greater than max(2 m, 0.5 % of the state miss distance) is rejected: one of them is wrong. |
| `RELATIVE_SPEED`, `RELATIVE_POSITION_R/T/N`, `RELATIVE_VELOCITY_R/T/N` | Only the unit label is checked. The values are not used, because Sentinel recomputes them from the states. |

**Used.**

| Keyword | Use |
|---|---|
| `MESSAGE_ID` | Stored and shown. A decision records the CDM it was made against by sha256 and message id. |
| `ORIGINATOR` | Data-class mark (below) and display. |
| `OBJECT_DESIGNATOR` | Event identity and object id. When absent, `OBJECT1` / `OBJECT2` stand in. |
| `OBJECT_NAME` | Display only. |
| `COLLISION_PROBABILITY` | Shown as the originator's Pc (`originator_pc`), beside Sentinel's own and never in place of it. |
| `AREA_PC` | Per-object hard-body radius, sqrt(A/π), used when both objects give one and there is no combined HBR. |
| `COMMENT HBR = <value> [m]` | Combined hard-body radius (the CARA and 19 SDS convention; 508.0-B-1 has no keyword for it). It takes precedence over `AREA_PC`. Unlabelled means metres. Any other label is ignored, not guessed at. With neither, the engine refuses a Pc (`NO_HBR`); the node's engine configuration sets no default radius. |

**Carried, not used.** Every other keyword is kept and forwarded but not
used in any computation. This covers `MESSAGE_FOR`,
`COLLISION_PROBABILITY_METHOD`, the screening-volume keywords, `OBJECT_TYPE`,
`MANEUVERABLE`, `CATALOG_NAME`, `INTERNATIONAL_DESIGNATOR`, `EPHEMERIS_NAME`,
`COVARIANCE_METHOD`, the orbit-determination and force-model parameters, and
the velocity, drag and SRP rows of the covariance. The 2D Pc uses the 3×3
position block only.

**Preserved.** The bytes are stored exactly as received. The sha256 is taken
over them, and a hub serves them unchanged to an edge, which checks the hash
end to end. The in-memory model also round-trips: `parse(emit(m)) == m` for
every keyword, unit label and `COMMENT` line.

## Units

An absent unit label is accepted as the standard's default. A label that is
present must match. The engine works in metres; states are converted from
km on the way in.

| Keywords | Required label | If labelled otherwise |
|---|---|---|
| `X` `Y` `Z` | `km` | `WRONG_UNIT`: quarantined |
| `X_DOT` `Y_DOT` `Z_DOT` | `km/s` | `WRONG_UNIT`: quarantined |
| `CR_R` `CT_R` `CT_T` `CN_R` `CN_T` `CN_N` | `m**2` | `WRONG_UNIT`: quarantined |
| `MISS_DISTANCE` `RELATIVE_POSITION_R` `RELATIVE_POSITION_T` `RELATIVE_POSITION_N` | `m` | `UNIT_LABEL_ANOMALY`: accepted, warned |
| `RELATIVE_SPEED` `RELATIVE_VELOCITY_R` `RELATIVE_VELOCITY_T` `RELATIVE_VELOCITY_N` | `m/s` | `UNIT_LABEL_ANOMALY`: accepted, warned |

The split follows the policy. A state in metres labelled as kilometres would
make every number wrong. A summary field with an odd label is an anomaly
worth recording, and nothing reads its value. NASA CARA's own AlfanoTestCase
CDMs label `RELATIVE_VELOCITY_*` as `[m]`; they are admitted with this
warning.

## Frames

States must be in an inertial frame. These are accepted:

| `REF_FRAME` | Note |
|---|---|
| `EME2000` | Treated as the same frame as GCRF. |
| `GCRF` | The frame bias to EME2000 is about 20 milliarcseconds, about 0.7 m at GEO radius, well inside any covariance a CDM carries. |

Any other value is rejected with `UNSUPPORTED_REF_FRAME`. ITRF is refused
rather than approximated, because converting it needs Earth-orientation data.
Covariance is read in each object's RTN frame, as the standard defines it.

## Rejection codes

Quarantined: the input would make the answer wrong.

| Code | Raised by | Meaning |
|---|---|---|
| `PARSE_ERROR` | codec | Not structurally a KVN CDM: a line that is not `KEY = VALUE`, other than two object blocks, objects out of order, or no `CCSDS_CDM_VERS`. |
| `UNREADABLE` | service | Structurally a CDM, but a value cannot be read: a non-numeric number, or bytes that are not UTF-8. |
| `MISSING_TCA` | validator | No `TCA`. |
| `BAD_TCA` | validator | `TCA` is not a CCSDS time. |
| `BAD_CREATION_DATE` | validator | `CREATION_DATE` is present but not a CCSDS time. |
| `MISSING_REF_FRAME` | validator | An object has no `REF_FRAME`. |
| `UNSUPPORTED_REF_FRAME` | validator | `REF_FRAME` is not an accepted inertial frame. |
| `WRONG_UNIT` | validator | A state or covariance term is labelled with a unit other than the one required. |
| `MISSING_STATE` | validator | An object lacks one of `X` `Y` `Z` `X_DOT` `Y_DOT` `Z_DOT`. |
| `NONFINITE_STATE` | validator | A state component is `NaN` or infinite. |
| `PARTIAL_COVARIANCE` | validator | Some but not all of the six position covariance terms are present and finite. |
| `MISS_DISTANCE_MISMATCH` | validator | The header `MISS_DISTANCE` disagrees with the distance between the two states by more than max(2 m, 0.5 %). |

The detail names the keyword and, where it applies, the object (`OBJECT1` or
`OBJECT2`).

## Warning codes

Accepted, degraded: the input limits what can be concluded without
corrupting it. Warnings are returned by the ingest call and stored with the
CDM (`history[].warnings` in `GET /api/events/{event_id}`).

| Code | Meaning | Consequence |
|---|---|---|
| `COVARIANCE_ABSENT` | An object has no position covariance. | Geometry only. The engine refuses a Pc with `NO_COVARIANCE`, correctly. |
| `UNIT_LABEL_ANOMALY` | A summary field carries a non-standard unit label. | None: the value is recomputed from the states. |

An admitted CDM can still be refused a Pc. A refusal is an assessment
result with a `RefusalReason`, not an admission code; see
`docs/risk-engine-design.md`.

## Event identity

CCSDS 508.0-B-1 has no event identifier, so the rule is explicit.

- **Grouping.** A CDM joins an existing event when it names the same ordered
  pair (`OBJECT1` designator, `OBJECT2` designator) and its `TCA` is within
  60 s of the event's reference TCA, which is the TCA of the event's first CDM.
  The pair is ordered, so a CDM with the objects swapped starts a different
  event.
- **New id.** `<OBJECT1 designator>-<OBJECT2 designator>-<TCA as YYYYMMDDThhmmss>`,
  for example `99001-99118-20260924T200000`. Designators are used as given.
  In a bus subject, any character other than a letter, a digit, `-` or `_`
  becomes `_`.
- **Assigned once.** Identity is assigned on the node where a CDM is first
  ingested and travels with the record (`Sentinel-Event-Id` on a sync fetch).
  An edge never re-derives it: updates fetched out of order would otherwise
  split one event into two. The edge takes the hub's identity as given and
  does not re-check the pair or TCA against it.
- **Content identity.** The sha256 of the bytes as received. The same bytes
  twice are a no-op. The same content with different whitespace is a
  different message.

## Data class

Every CDM is `REAL`, `DERIVED` or `EXERCISE`. Sentinel's own generators mark
their messages at the source, and that mark decides the class, whatever
route the message arrived by. The comparison ignores case.

| ORIGINATOR | Data class | Produced by |
|---|---|---|
| `SENTINEL-EXERCISE` | `EXERCISE` | The exercise scenario (`sentinel/conjunction/exercise.py`). |
| `SENTINEL-SCREENING` | `DERIVED` | Demonstration-mode screening (`sentinel/screening/derived_cdm.py`, ADR-002). |
| anything else | as the route says | See the table at the top. |

### How a DERIVED (screening) CDM is marked

- `ORIGINATOR = SENTINEL-SCREENING`.
- `COMMENT Demonstration mode: element-set geometry only; no probability of collision (ADR-002)`
- `COMMENT DERIVED data: SGP4 on public element sets, kilometre-scale error, no covariance`
- No covariance block and no `COVARIANCE_METHOD`. 508.0-B-1 makes both
  mandatory, and there is nothing true to write in either, so the message
  is deliberately non-conformant there. Both objects therefore warn
  `COVARIANCE_ABSENT`, and the engine refuses a Pc with no screening branch
  in its code.
- `OBJECT_TYPE = UNKNOWN`, `MANEUVERABLE = N/A`, `REF_FRAME = GCRF`, and
  `MESSAGE_ID = SCREEN-<primary>-<secondary>-<TCA>`. Each object block's
  comment names the element set it came from by sha256.

### How an EXERCISE CDM is marked

- `ORIGINATOR = SENTINEL-EXERCISE`.
- `COMMENT EXERCISE EXERCISE EXERCISE - synthetic data, not a real conjunction`
- Fictional designators in the 99xxx range, and object names ending
  `(EXERCISE)`.
