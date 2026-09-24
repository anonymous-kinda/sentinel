# Wayfinder adapter

> **Disclaimer.** Wayfinder is a product of Privateer Space. Sentinel is an
> independent open-source project. It is not affiliated with, sponsored by
> or endorsed by Privateer Space. Wayfinder is named here only as an
> integration target.

## Status: assumed schema, not yet validated

Wayfinder offers ephemeris download through an API. Its schema is not
public to this project, so `sentinel/adapters/wayfinder.py` parses a shape
that Sentinel **assumed**. **The adapter must be validated against the real
API when access is granted.** Until then, the assumption is labelled
everywhere it appears:

- The module declares `SCHEMA_STATUS = "ASSUMED"`, and every parse logs
  `Ephemeris parsed from assumed schema` with `adapter=wayfinder`.
- The contract fixture is `fixtures/wayfinder/ASSUMED-ephemeris-worldview3.json`.
  It labels itself `"schema": "ASSUMED"` and `"data_class": "DERIVED"`, and it
  states that it is not Wayfinder output.
- The fixture's numbers are the public CelesTrak element set for
  WORLDVIEW-3, propagated with SGP4 by `scripts/make_assumed_wayfinder_fixture.py`.
  They are never presented as Wayfinder data. The contract test re-derives
  every position from the element set. See `fixtures/wayfinder/PROVENANCE.md`.

## The assumed shape

```json
{
  "object": {"norad_id": 40115, "name": "WORLDVIEW-3 (WV-3)"},
  "frame": "ITRF",
  "time_system": "UTC",
  "created": "2026-09-23T22:37:02.779392Z",
  "epochs": ["2026-09-24T05:00:00Z", "2026-09-24T05:01:00Z"],
  "positions_km": [[-544.405958, -6598.970852, -2257.76234], [-649.568678, -6720.66173, -1829.001999]]
}
```

Unknown keys are ignored, so a richer real payload still parses.

## What comes out, and what is refused

The adapter's output is a `StateTable`, the same input the
tabulated-ephemeris pass provider takes from a CCSDS OEM. Admission follows
the repository rule: input that would make the answer **wrong** raises
`EphemerisRejected` with a stable code.

| Code | Cause |
|---|---|
| `SCHEMA_MISMATCH` | a field is missing or has the wrong type, or the body is not a JSON object |
| `REF_FRAME_NOT_EARTH_FIXED` | the frame is not an ITRF realisation. Inertial data would need an Earth-orientation transform, which is refused rather than approximated |
| `TIME_SYSTEM_NOT_UTC` | TAI or GPS time would shift every pass by 37 s or 18 s |
| `MALFORMED_TIME`, `NAIVE_TIME` | the time is not ISO 8601, or has no zone |
| `EPOCHS_NOT_INCREASING`, `SHAPE_MISMATCH`, `MALFORMED_NUMBER` | the table cannot be interpolated honestly |

```
Wayfinder JSON ─▶ adapters.wayfinder.parse_ephemeris ─▶ StateTable ─▶ TabulatedEphemerisProvider ─▶ PassWindow
CCSDS OEM      ─▶ ephemeris.oem.parse + admit       ─▶ StateTable ─┘
OMM            ─▶ SGP4 provider ────────────────────────────────────────────────────────────────▶ PassWindow
```

Both providers are held to the same conformance suite
(`tests/conformance/test_pass_providers.py`), including a brute-force oracle.

## Swapping in the real schema

1. **Get a real response** and the API's statement of frame, time system and
   units. Check that its licence allows committing a sample. If it does not,
   commit a hand-reduced excerpt, or keep the fixture out of the repository.
2. **Record provenance.** Save it under `fixtures/wayfinder/`. Record its
   source, retrieval date and SHA-256 in `PROVENANCE.md` and `SHA256SUMS`, as
   `fixtures/omm/` does.
3. **Change one function.** `parse_ephemeris` is the only code that knows the
   shape. Map the real fields to a `StateTable`, and pass the real frame and
   time system through `require_earth_fixed` and `require_utc`. If the
   product is inertial (EME2000, GCRF) or is not on UTC, it will be refused
   until a conversion is added deliberately, with its own tests and ADR.
4. **If the product is a CCSDS OEM, write no parser.** Call
   `sentinel.ephemeris.oem.parse` and then `admit`.
5. **Repoint the contract test.** In `tests/adapters/test_wayfinder.py`, keep
   the error-case tests. Replace the provenance tests, which re-derive the
   assumed fixture from the element set, with checks against the real
   response's documented values.
6. **Drop the label.** Set `SCHEMA_STATUS` to `"VALIDATED"` and record the
   API version it was validated against. Change the log message to match.

Nothing downstream changes, because the provider only ever sees a `StateTable`.

## Not in scope

The adapter parses bytes. It does not fetch them. An API client (keys, rate
limits, retries) belongs in its own module. An air-gapped edge node receives
tables through the sync layer rather than calling out.
