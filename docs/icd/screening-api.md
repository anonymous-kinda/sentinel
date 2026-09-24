# Interface control: demonstration-mode screening HTTP API

Demonstration mode (ADR-002). Public element sets carry kilometre-scale
error and no covariance, so this interface returns geometry (when, how
close, how fast) and **never a probability of collision**. Each close
approach is ingested as a DERIVED CCSDS CDM with no covariance, through the
same path as any other CDM, so it appears in `GET /api/events` with its Pc
refused by the engine's existing `NO_COVARIANCE` gate. Times are ISO 8601
UTC.

The screening runs against the element sets on the node that receives the
request: a hub's vendored or configured snapshot, or what an edge has
synced from its hub. Nothing is fetched from anywhere else.

## Screen

`POST /api/screening` with a JSON body:

```json
{"primary_norad_id": 40115, "hours": 24, "threshold_km": 5}
```

| field | type | default | allowed |
|---|---|---|---|
| `primary_norad_id` | integer | required | positive; must have an element set on this node |
| `hours` | number | 24 | 0 < hours ≤ 72 |
| `threshold_km` | number | 5 | 0 < threshold_km ≤ 50 |

The window starts at the node's clock (`now`) and runs `hours`.

Status codes:

- `200`: screened, with zero or more approaches.
- `403`: the node is read-only (screening writes DERIVED CDMs).
- `404`: no element set for the primary on this node. Body:
  `{"detail": {"code": "UNKNOWN_PRIMARY", "reason": "..."}}`.
- `422`: wrong input (missing or non-integer primary, a value out of range,
  an unknown field, a body that is not a JSON object), or a primary whose
  element set SGP4 cannot propagate. The latter carries
  `{"detail": {"code": "...", "reason": "..."}}`.

Response (the values are illustrative; the shape is the contract):

```json
{
  "mode": "DEMONSTRATION",
  "note": "element-set geometry only; no probability of collision (ADR-002)",
  "primary": {"norad_id": 40115, "name": "WORLDVIEW-3 (WV-3)"},
  "start": "2026-09-24T06:00:00+00:00",
  "end": "2026-09-24T12:00:00+00:00",
  "hours": 6,
  "threshold_km": 10,
  "screened": 166,
  "after_prefilter": 40,
  "runtime_s": 0.412,
  "approaches": [
    {"secondary": {"norad_id": 99115, "name": "CROSSER 90 (TEST)"},
     "tca": "2026-09-24T06:41:12.345000+00:00",
     "miss_distance_km": 1.234, "relative_speed_km_s": 10.9,
     "event_id": "40115-99115-20260924T064112",
     "ingest": "accepted",
     "data_class": "DERIVED",
     "assessment": {"method": "REFUSED", "refusal_reason": "NO_COVARIANCE"}}
  ],
  "skipped": [{"norad_id": 0, "code": "UNUSABLE_ELEMENTS", "detail": "..."}]
}
```

- `screened`: objects screened against the primary (every element set on
  the node except the primary). `after_prefilter`: of those, how many passed
  the apogee/perigee filter and were propagated.
- `approaches`: in TCA order. `tca` is the CDM's TCA, rounded to the
  millisecond. `miss_distance_km` and `relative_speed_km_s` are the
  screening's own geometry.
- `ingest`: what the conjunction service did with the DERIVED CDM:
  `accepted`, `duplicate` (the same CDM bytes were ingested before, for
  example a repeat request against a frozen clock) or `rejected`.
  `event_id` names the event it was filed under, a duplicate included.
- `assessment`: the engine's method and refusal reason for that event's
  latest CDM. Only `method` and `refusal_reason` are carried: there is no
  Pc to carry.
- `skipped`: secondaries SGP4 could not propagate. They are named, and the
  rest are still screened (the answer is incomplete and says so). A primary
  that cannot be propagated refuses the whole request (`422`).
