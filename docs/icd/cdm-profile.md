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
  anywhere and are kept verbatim, in place. A keyword appears at most once in
  a block. The header and relative metadata together are one block, and
  each object is another.
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
| `TCA` | relative metadata | Must be present, a CCSDS time, and no earlier than 1957-10-04. |
| `OBJECT` | each object | `OBJECT1`, then `OBJECT2`, exactly two blocks. |
| `REF_FRAME` | each object | One of the accepted frames (below). |
| `X` `Y` `Z` `X_DOT` `Y_DOT` `Z_DOT` | each object | Present, finite, in the required units, and within the physical bounds (below). |

**Checked when present.**

| Keyword | Rule |
|---|---|
| `CREATION_DATE` | Must be a CCSDS time, and no earlier than 1957-10-04. It also stamps the record's creation time in the sync manifest; without it, the time of receipt is used. |
| `CR_R` `CT_R` `CT_T` `CN_R` `CN_T` `CN_N` | Position covariance in the object's RTN frame. All six finite, or none: a partial covariance is rejected rather than completed by invention. None is accepted with a warning, and the engine then refuses a Pc (`NO_COVARIANCE`). A `NaN` counts as absent. Each term must be within the physical bounds (below). |
| `MISS_DISTANCE` | Cross-checked against the states. A disagreement greater than max(2 m, 0.5 % of the state miss distance) is rejected: one of them is wrong. |
| `RELATIVE_SPEED`, `RELATIVE_POSITION_R/T/N`, `RELATIVE_VELOCITY_R/T/N` | Only the unit label is checked. The values are not used, because Sentinel recomputes them from the states. |

**Used.**

| Keyword | Use |
|---|---|
| `MESSAGE_ID` | Stored and shown. A decision records the CDM it was made against by sha256 and message id. |
| `ORIGINATOR` | Data-class mark (below) and display. |
| `OBJECT_DESIGNATOR` | Event identity and object id. When absent, `OBJECT1` / `OBJECT2` stand in. |
| `OBJECT_NAME` | Display only. |
| `COLLISION_PROBABILITY` | Shown as the originator's Pc (`originator_pc`), beside Sentinel's own and never in place of it. It must be a finite number. |
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

## Physical bounds

A CDM screens objects in orbit about the Earth. A state that no such object
can have is wrong, not unusual: the engine would still compute a Pc from a
state faster than light. Such a message is quarantined with
`IMPLAUSIBLE_STATE`, before any of its numbers are converted to metres. The
bounds come from physics and are set generously, so that no real CDM comes
near them.

| Quantity | Admitted | Why |
|---|---|---|
| Position magnitude | 6,356.752 km to 3,000,000 km | The lower bound is the WGS-84 polar radius, the closest the Earth's surface comes to its centre. A point inside it is underground at every latitude. The upper bound is twice the distance to the Sun–Earth L1 and L2 points (about 1.5 million km). Spacecraft on halo and Lissajous orbits there reach about 1.8 million km from the Earth and straddle its Hill sphere, a·(m⊕ / 3M☉)^(1/3) ≈ 1.5 million km, so the Hill sphere itself would quarantine real CDMs. The bound also holds the Moon (at most 405,500 km away) with a wide margin. |
| Speed | at most 100 km/s | Every orbit about the Earth is slower than escape speed, which is highest at the lowest radius admitted: √(2μ/b) = 11.2 km/s. A departing probe is faster (New Horizons left at 16.3 km/s). Nothing bound to the Sun passes the Earth faster than about 73 km/s: solar escape speed at 1 au (42.1 km/s) plus the Earth's orbital speed (29.8 km/s), raised slightly by the Earth's own pull. 100 km/s is about nine times escape speed and still 3,000 times slower than light. |
| Each position covariance term | magnitude at most `9e+18` m**2 | The admitted radius squared, (3 × 10⁹ m)². A coordinate confined to ±R has a variance of at most R² (Popoviciu's inequality), and no covariance term is larger than the variances beside it (Cauchy–Schwarz). A larger term describes no object inside the admitted region. |

- **Order.** The state is checked once it is known to be finite, position
  before speed. The covariance is checked after `PARTIAL_COVARIANCE`. A `NaN`
  or infinite term keeps its meaning above: absent, or partial.
- **A unit error is caught too.** A position written in metres under a `km`
  label reads as at least 6.36 million km, beyond the admitted radius.
- **No real CDM comes near.** Every NASA CARA fixture is admitted
  (`tests/test_cdm_codec.py`). They lie between 6,700 and 46,000 km, move
  below 10 km/s, and carry no covariance term above 10¹³ m**2.
- **Sun–Earth libration orbits are admitted.** Spacecraft about the Sun–Earth
  L1 and L2 points sit near 1.5 million km, and their halo orbits reach about
  1.8 million km. The 3 million km bound holds them with margin
  (`tests/test_ingest_hostile.py`).
- **An orbit has angular momentum.** A velocity of zero, or one along the
  position (the sine of the angle between them below `1e-12`), leaves no
  orbital plane. The covariance is written in RTN, which that plane defines,
  so the message is quarantined as `IMPLAUSIBLE_STATE`. The engine also
  refuses such a state (`INVALID_COVARIANCE`, stage `rtn_frame`) if one ever
  reaches it another way.
- The trajectory view (`sentinel/conjunction/trajectory.py`) draws arcs only
  within the same radius band.

## Rejection codes

Quarantined: the input would make the answer wrong.

| Code | Raised by | Meaning |
|---|---|---|
| `PARSE_ERROR` | codec | Not structurally a KVN CDM: a line that is not `KEY = VALUE`, other than two object blocks, objects out of order, or no `CCSDS_CDM_VERS`. Also a keyword given twice in one block: which value was meant would be a guess. |
| `UNREADABLE` | validator, service | Structurally a CDM, but a value cannot be read: a non-numeric number, or bytes that are not UTF-8. Also a `COLLISION_PROBABILITY` that is `NaN` or infinite: it is served beside Sentinel's Pc and must be a number. |
| `MISSING_TCA` | validator | No `TCA`. |
| `BAD_TCA` | validator | `TCA` is not a CCSDS time, or not a date the calendar has (past 9999-12-31, which a day-of-year form can reach). Also a `TCA` before 1957-10-04, the launch of Sputnik 1: no conjunction precedes the first artificial satellite. |
| `BAD_CREATION_DATE` | validator | `CREATION_DATE` is present but fails the same test as `BAD_TCA`: not a CCSDS time, past 9999-12-31, or before 1957-10-04. |
| `MISSING_REF_FRAME` | validator | An object has no `REF_FRAME`. |
| `UNSUPPORTED_REF_FRAME` | validator | `REF_FRAME` is not an accepted inertial frame. |
| `WRONG_UNIT` | validator | A state or covariance term is labelled with a unit other than the one required. |
| `MISSING_STATE` | validator | An object lacks one of `X` `Y` `Z` `X_DOT` `Y_DOT` `Z_DOT`. |
| `NONFINITE_STATE` | validator | A state component is `NaN` or infinite. |
| `IMPLAUSIBLE_STATE` | validator | A state or position covariance no Earth-orbiting object can have: a position inside the Earth or beyond 3 million km, a speed above 100 km/s, no angular momentum (a zero velocity, or one along the position), or a covariance term wider than that radius squared. See "Physical bounds" above. |
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
  pair (`OBJECT1` designator, `OBJECT2` designator), has the same data class,
  and its `TCA` is within 60 s of the event's reference TCA, which is the TCA
  of the event's first CDM. An event holds one data class: a screening CDM
  (DERIVED, geometry only) never becomes the latest CDM of a REAL event.
  The pair is ordered, so a CDM with the objects swapped starts a different
  event.
- **New id.** `<OBJECT1 designator>-<OBJECT2 designator>-<TCA as YYYYMMDDThhmmss>`,
  for example `99001-99118-20260924T200000`. Designators are used as given.
  When an event of another data class already holds that id, the new event's
  id has its data class appended, for example
  `99001-99118-20260924T070000-DERIVED`.
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
