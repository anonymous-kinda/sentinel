# Interface control: pass module HTTP API

Edge-local. Nothing on this interface is a sync record; the unit's position
and its pass windows never leave the node (ADR-010). Times are ISO 8601 UTC.
The module reports itself as `"passes"` in `GET /api/node` → `modules`.

## Unit

`GET /api/passes/unit` → `200 Unit` or `404` when no unit is set.

`PUT /api/passes/unit` with a `Unit` body → `200 Unit`. `403` on a read-only
node. `422` on a unit the node cannot compute for. Its `detail` names the
`field` and gives a `reason`, never the submitted value:

- a body that is not a JSON object, or a field a unit does not have;
- `unit_id`, `lat_deg` or `lon_deg` missing (`alt_m` defaults to 0 and
  `reaction_time_min` to 30);
- a `unit_id` that is not a string, is blank, or is over 64 characters;
- a coordinate, altitude or reaction time that is not a finite number;
- latitude outside [-90, 90], or longitude outside [-180, 180];
- altitude outside [-500, 9000] m. That runs from below the Dead Sea shore
  (about -430 m) to above Everest (8,849 m), with a margin;
- reaction time not positive or over 4320 min. That is the 72 hours of the
  longest interval the node computes, and a longer gap could never be
  found.

`DELETE /api/passes/unit` → `204`.

```json
{"unit_id": "EX-UNIT-1", "lat_deg": 35.26, "lon_deg": -116.68, "alt_m": 700.0, "reaction_time_min": 30.0}
```

## Windows and gaps

`GET /api/passes?hours=24` (1 to 72) → `409` when no unit is set, else:

```json
{
  "unit": {"unit_id": "EX-UNIT-1", "lat_deg": 35.26, "lon_deg": -116.68, "alt_m": 700.0, "reaction_time_min": 30.0},
  "start": "2026-09-24T06:00:00+00:00",
  "end": "2026-09-25T06:00:00+00:00",
  "provider": "skyfield-local",
  "label": "not observed by catalogued imagers",
  "windows": [
    {"norad_id": 40115, "name": "WORLDVIEW-3 (WV-3)", "sensor": "EO",
     "rise": "...", "culmination": "...", "set": "...",
     "padded_start": "...", "padded_end": "...", "pad_s": 75.0,
     "max_elevation_deg": 61.2, "mask_elevation_deg": 40.3,
     "element_age_days": 0.5, "stale": false, "sunlit": true, "usable": true}
  ],
  "gaps": [{"start": "...", "end": "...", "duration_s": 5400.0, "low_confidence": false}],
  "next_unobserved": {"start": "...", "end": "...", "duration_s": 5400.0, "low_confidence": false},
  "catalog": {"imagers": 38, "skipped": [{"norad_id": 0, "name": "...", "reason": "..."}]},
  "elements": {"oldest_age_days": 0.9, "newest_age_days": 0.1, "stale": 0}
}
```

- `windows`: every pass overlapping the interval, sorted by rise, including
  unusable ones (EO at night) so the operator sees them; `usable` says which
  count against the unit.
- `gaps`: the interval minus padded usable windows. A gap is time *not
  observed by catalogued imagers* - never "safe": uncatalogued and
  non-public sensors are outside this model.
- `next_unobserved`: the first gap at least `reaction_time_min` long that
  ends after now, or `null`.
- `low_confidence` / `stale`: an element set older than 3 days fed the result.

## Catalog

`GET /api/passes/catalog` →

```json
{"imagers": [{"norad_id": 40115, "name": "WORLDVIEW-3 (WV-3)", "sensor": "EO",
              "max_off_nadir_deg": 45.0, "gsd_m": 0.31, "basis": "...",
              "element_epoch": "...", "element_age_days": 0.5, "stale": false}],
 "skipped": [{"norad_id": 0, "name": "...", "reason": "..."}]}
```

## Tracks (visualization only)

`GET /api/passes/tracks?norad_id=40115&start=...&end=...` (at most 30 min) →
`{"norad_id": 40115, "positions_ecef_m": [[x, y, z], ...], "step_s": 20, "note": "visualization only"}`.
