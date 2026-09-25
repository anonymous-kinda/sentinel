# 10. Passes and screening

## What you will learn

- How the pass module answers one question for a ground unit: when can a catalogued imaging satellite see it, and when can none?
- The geometry behind the answer: the mask elevation from a field of regard, sunlight, and a timing pad that grows as element sets age.
- Why two pass providers sit behind one contract, and how one conformance suite holds them both to a brute-force oracle.
- How the unit's position is kept on its edge node by four independent layers, and how the OPSEC harness scenario proves it.
- How demonstration-mode screening finds close approaches from public element sets and still never prints a probability of collision.

## Why it exists

A ground unit wants to know when it can be seen from orbit. The honest answer it can get from public data is narrower than "am I safe": it is *when is no catalogued public imager, under stated assumptions, in a position to see me?* The pass module computes that on the edge node that serves the unit's operator. It uses public element sets the node already holds, so it keeps working with the link to the hub cut.

The input is the most sensitive fact in the system: where the unit is. The hub never needs it, so it never gets it. The design removes the flow rather than protecting it (ADR-010).

Screening is the second job in this chapter. With only public element sets, a node can still say which objects pass close to a primary satellite, and when. It cannot say how likely a collision is, because element sets carry no covariance. Screening therefore produces geometry and files each approach as a CDM the risk engine is certain to refuse (ADR-002).

## Concepts

### Element sets and their age

An **element set** (a TLE, or its modern form, an OMM record) is a compact description of an orbit at one instant, its **epoch**. The SGP4 propagator turns it into a position at any other time. SGP4 is fast and good to about a kilometre near the epoch. Its error grows with time from the epoch, mostly along the track: the satellite arrives a little early or late. Sentinel's snapshot is `fixtures/omm/celestrak-resource-20260924.json`, a public CelesTrak download with provenance in `fixtures/omm/PROVENANCE.md`.

The **age** of an element set at some moment is that moment minus its epoch. Everything in this chapter that depends on trust depends on age.

### A pass, and the mask elevation

Seen from the unit, a satellite rises, climbs to its highest **elevation** (the **culmination**), and sets. An imager does not see everything above the horizon. It can point at most some angle away from straight down, its **off-nadir** limit or **field of regard**. That limit fixes the lowest elevation, seen from the ground, at which the imager can still see the unit. That elevation is the **mask**. A **pass** is the time the satellite spends above the mask.

```
                S          satellite, R + h from the Earth's centre
               /|
              / |          angle at S, between S->G and S->O: the off-nadir angle
             /  |
            /   |
 horizon --G    |          angle at G, above the horizon: the elevation
            \   |
           R \  |  R + h
              \ |
               \|
                O          Earth's centre

 law of sines in the triangle O-G-S:   sin(off_nadir) = R / (R + h) * cos(elevation)
```

Solve for the elevation at the imager's off-nadir limit and you have the mask. A narrow sensor gets a high mask; a wide one gets a low mask, and past a certain width the imager can see the horizon and the mask is zero. With the code's own function (`min_elevation_deg`):

| Off-nadir limit | Altitude | Mask elevation |
|---|---|---|
| 7.5° (a nadir-pointing Landsat) | 705 km | 81.7° |
| 30° | 617 km | 56.7° |
| 45° | 617 km | 39.1° |
| 70° | 617 km | 0° (horizon-limited) |

### Usable passes: sunlight

An optical (EO) imager needs the unit lit. The module calls a pass **usable** when the sensor is radar (SAR), or when it is optical and the sun is at least 10° above the unit's horizon at culmination. A night pass of an optical imager is still reported, so the operator sees it, but it observes nothing.

### The timing pad and staleness

Because along-track error grows with age, every window is widened by a **pad** of 60 s plus 30 s per day of element-set age: 60 s for a fresh set, 150 s at three days. At more than three days a set is **stale**. A stale set is still used, because a cut-off edge still needs an answer, but everything it touches is flagged.

### Gaps: the complement of observed time

A **gap** is time in the requested interval that no padded, usable window covers.

```
 interval  |--------------------------------------------------------|
 SAR       |      [==pad==|pass|==pad==]                            |
 EO (day)  |                      [=|pass|=]          [=|pass|=]    |
 EO (night)|                                 (x night: unlit x)     |
 gaps      |<---->                          <-------->          <-->|
```

The SAR window and the first daylight window overlap once padded, so they merge into one observed span. The night pass does not close the gap it sits in.

A gap is labelled `"not observed by catalogued imagers"`. It is never called safe: uncatalogued and non-public imagers, aircraft and ground sensors are outside this model. The pad makes gaps shorter, never longer. So does every other assumption in the module, on purpose: the dangerous error for this product is a gap that looks longer than it is.

The **next unobserved** gap is the first one that still has at least the unit's **reaction time** left to run. It answers the practical question: when is my next chance to move unobserved?

### One contract, two providers

A **pass provider** takes a unit, a list of imagers and an interval, and returns windows. There are two:

- `skyfield-local` propagates element sets with SGP4.
- `tabulated-ephemeris` never propagates. It interpolates a table of Earth-fixed positions that someone else produced: a CCSDS OEM file, or a source adapter's output.

They share no computation. They agree only because they follow one contract, the **overlap convention**: return every pass that overlaps the interval, with its *true* rise, culmination and set even when those fall outside it.

```
 interval           |=====================================|
 pass A        <----+---->             returned whole, rise before the interval
 pass B                       <------->   returned
 pass C                                          <--------+--->  returned whole
 pass D  <---->                                            not returned: no overlap
```

The caller clips. A second contract rule matters more: a provider asked about an imager it has no data for raises `ImagerNotCovered`. It never skips the imager, because a silently missing imager makes every gap look longer.

### OPSEC as architecture

The unit's position, and every window and gap computed from it, exist only on the edge node. Four independent layers enforce that (ADR-010):

```
 edge node                                                    hub
 +-------------------------------------------------+       +-------------+
 | PUT /api/passes/unit                             |       |             |
 |    -> UnitFile  <SENTINEL_VAR>/unit.json, 0600   | 3     |  public     |
 |    -> PassService  (logs "Unit set", no fields)  | 2     |  element    |
 |          ^                                       |       |  sets       |
 |          | element sets, pulled by sync   <------+-------+  (omm:*)    |
 |          |  (the unit is not a record)           | 1     |             |
 |    node.<id>.passes.updated  {reason, version}   | 2     |             |
 | nats-server leaf: deny_exports unit.> passes.>   |       |             |
 |                   node.>                         | 4  X  |             |
 +-------------------------------------------------+       +-------------+
   1 data model   2 application   3 storage   4 transport
```

If any one layer fails, the others still hold. An application bug that publishes the unit on `unit.x`, for example, stops at the edge's own nats-server.

### Demonstration-mode screening

Screening asks: which objects come within a threshold distance of a primary satellite in the next few hours, and when? The time of closest approach (**TCA**) is where the range between the two stops shrinking and starts growing, that is, where the **range rate** crosses zero from closing to opening. Screening finds those zeros from element sets and reports geometry only. The risk engine computes a probability of collision (Pc) only from covariance, and element sets have none, so each approach is written as a DERIVED CDM with no covariance block. The engine's `NO_COVARIANCE` gate refuses it, with no special case for screening anywhere in the engine.

## Code walkthrough

Read the pass module first, from its contract outwards, then the ephemeris and adapter packages that feed its second provider, then screening.

### 1. `sentinel/passes/model.py`: the contract

`Unit`, `Imager` and `PassWindow` are frozen dataclasses; `PassProvider` is a `Protocol`. `PassWindow` derives what the rest of the module needs from its own fields: `pad_s`, `padded`, `stale` and `usable`. `ImagerNotCovered` is the coverage rule in code. `MIN_HOURS` and `MAX_HOURS` (1 and 72) bound every pass answer.

*Easy to get wrong:* `usable` is `sensor != "EO" or bool(sunlit)`. SAR windows carry `sunlit=None` and are always usable. Do not test `sunlit` alone.

### 2. `sentinel/passes/geometry.py` and `sentinel/passes/topocentric.py`: the maths

`min_elevation_deg` is the law-of-sines mask above, on a spherical Earth. `sun_elevation_deg` is the Astronomical Almanac's low-precision solar formula, checked against JPL DE421 in `tests/passes/test_geometry.py`. `element_pad_s` is the pad, and `STALE_AFTER_DAYS` and `EO_MIN_SUN_ELEVATION_DEG` are the two planning constants every provider shares.

`Site` in `topocentric.py` puts the unit on the WGS84 ellipsoid instead, for the provider that works from Earth-fixed positions. Its docstring says why: the vertical differs by up to 0.19°, which matters when the mask is at 80°.

*Easy to get wrong:* two Earth models coexist on purpose. The mask uses a sphere; elevation from a table uses the ellipsoid. Do not "fix" one to match the other without re-running the conformance suite.

### 3. `sentinel/passes/catalog.py` and `sentinel/passes/imaging.toml`: which imagers count

`imaging.toml` lists 38 public imagers (29 EO, 9 SAR). Each `max_off_nadir_deg` is a planning assumption with its source in `basis`. `load_catalog` refuses anything that would make a prediction wrong, with `CatalogError`: an unknown sensor, an angle outside (0, 90), a duplicate NORAD id, a missing field, blank text.

*Easy to get wrong:* the assumptions err **wide**, deliberately. A wider field of regard lowers the mask, lengthens windows and shortens gaps. SAR entries record the maximum *incidence* angle as off-nadir, which overstates reach; that is the conservative direction here. If you tighten an entry to be "more accurate", you move the error towards longer gaps.

### 4. `sentinel/passes/elements.py` and `sentinel/passes/element_store.py`: element sets

These two files are easy to confuse. The node's store is `ElementStore`:

- `add` parses one record (`PARSE_ERROR` if it is not a JSON object), validates it with `validate_omm` (`MISSING_FIELD`, `INVALID_FIELD`), and returns `accepted`, `duplicate` or `superseded`. It keeps only the newest epoch per object.
- `version` counts accepted sets. It changes exactly when `latest()` does, so anything computed from the store can be cached against it.
- A record's bytes are its canonical JSON (`canonical_bytes`), so every node derives the same sha256 from the same element set. Sync names records by that hash.

`elements.py` holds the helpers the providers use (`epoch_utc`, `orbital_period_s`, `mean_altitude_km`) and the catalog matcher. `match_catalog` pairs each imager with its element set and returns a `Match` with the `skipped` ones and why: `MISSING`, or `NAME_MISMATCH` when the NORAD id now belongs to a different object. Names match only as the whole catalog name, or the name followed by a space, so `SKYSAT-C1` does not match `SKYSAT-C10`. `load_omm` is a strict loader used by `scripts/bench_passes.py` and the tests, not by a node.

*Easy to get wrong:* a skipped imager is not an error. It is logged (`Imager skipped`) and reported, and the service then marks every gap low confidence.

### 5. `sentinel/passes/providers/`: two implementations of one contract

**`skyfield_local.py`, `SkyfieldProvider`.** For each imager:

1. find its element set, or raise `ImagerNotCovered`;
2. refuse a set whose period exceeds 128 min (`MAX_LEO_PERIOD_S`), because the search assumes a pass is shorter than an orbit;
3. compute the mask from the set's mean altitude;
4. search one orbital period either side of the interval, so passes that overlap its ends are found whole;
5. keep the passes that overlap, and build each `PassWindow` with its age at culmination and its daylight verdict.

It loads Skyfield's bundled timescale only: no JPL file and no network.

**`skyfield_passes.py`** exists because a 1 s brute-force oracle (`tests/passes/test_oracle.py`) caught Skyfield's event finder reporting rises up to 0.5 s late. `find_passes` groups the finder's events into whole passes (`_whole_passes`), then `_refine` bisects each rise and set to a millisecond and reports the end of the bracket that lies *below* the mask. A window therefore always contains the true pass. It errs towards observed time, never towards a gap.

**`tabulated.py`, `TabulatedEphemerisProvider`.** It samples elevation every 30 s over the interval plus 30 min either side, clipped to the table. Each local maximum is refined with bounded Brent, and the mask is computed at the altitude of that culmination. Rise and set are found with `brentq` between the culmination and the nearest coarse sample below the mask on each side. `element_age_days` is the product's age at culmination (`culmination - table.created`), so the same pad applies. It never extrapolates.

**The conformance suite**, `tests/conformance/test_pass_providers.py`, runs every test once per factory in `PROVIDER_FACTORIES`. The factories are in `tests/conformance/factories.py`. It checks the overlap convention, sorting, that each window names its provider, that an uncovered imager raises, and agreement with the brute-force oracle in `tests/conformance/oracle.py`: the same passes, rise and set within 2 s, maximum elevation within 0.1°.

*Easy to get wrong:* the tabulated provider is not wired into a running node. `PassService` takes a `provider_factory`, and the default is `SkyfieldProvider`. The tabulated provider is proven against the contract, not deployed.

### 6. `sentinel/ephemeris/` and `sentinel/adapters/wayfinder.py`: feeding the second provider

`sentinel/ephemeris/table.py` defines `StateTable` and the admission rules every table source shares. Input that would make an answer wrong raises `EphemerisRejected` with a stable code. That means an inertial frame (`REF_FRAME_NOT_EARTH_FIXED`: converting it would need Earth-orientation data), a time system other than UTC, epochs that do not increase, a non-finite number or a naive time. `interpolate.py` is a degree-8 Lagrange interpolator. It refuses a table with a step over 300 s (`STEP_TOO_COARSE`), with the measured interpolation error in its docstring. `oem.py` parses a single-segment CCSDS OEM and `admit`s it: missing velocities are admitted with a `VELOCITY_ABSENT` warning, because positions are all the provider uses. `tabulate.py` samples a Skyfield satellite into a table, which is how the conformance suite builds tables.

`sentinel/adapters/wayfinder.py` maps a Wayfinder ephemeris payload to a `StateTable`. Wayfinder is a product of Privateer Space. The schema is **assumed**, since it is not public to this project, and Sentinel is not affiliated with or endorsed by Privateer Space (`docs/adapters/wayfinder.md`). `SCHEMA_STATUS = "ASSUMED"`, every parse logs `Ephemeris parsed from assumed schema`, and `parse_ephemeris` is the only function that knows the shape.

*Easy to get wrong:* `.importlinter` keeps `sentinel.ephemeris` below the pass module and the adapters. Its one allowed edge into `sentinel.cdm` is the shared CCSDS time parser.

### 7. `sentinel/passes/gaps.py`: from windows to gaps

`unobserved_gaps` merges the padded spans of usable windows (`_merge`) and takes their complement over the interval (`_complement`). A gap is `low_confidence` when any stale window, usable or not, touches it. `next_unobserved` returns the first gap with at least `min_duration` left after `now`; a gap already in progress is returned starting at `now`.

*Easy to get wrong:* the pad is applied *before* merging, so two windows whose pads overlap leave no gap between them. `tests/passes/test_gaps.py` includes a property test that gaps are exactly the time no padded usable window covers.

### 8. `sentinel/passes/unit.py`: the unit on disk

`unit_from_dict` validates a body and raises `UnitRejected(field, detail)`. The detail never contains the submitted value, so coordinates cannot leak through error text or logs. The bounds: latitude in [-90, 90], longitude in [-180, 180], altitude in [-500, 9000] m (below the Dead Sea shore to above Everest, with a margin), and reaction time positive and at most 4320 min. A reaction time longer than the 72-hour maximum interval could never find a gap.

`UnitFile` is the only place a unit is stored. `save` calls `replace_durably`: write a temporary file with mode 0600, fsync it, rename it over the old one, then fsync the directory. A reader sees the old unit or the new one, never half, and a power cut leaves one or the other.

*Easy to get wrong:* the file is private from its first byte. `tempfile.mkstemp` creates it with mode 0600, and `os.fchmod` sets the requested mode before anything is written, so there is no moment when the position sits in a world-readable file. Writing to the final path and calling `chmod` afterwards would leave one.

### 9. `sentinel/passes/service.py` and `sentinel/api/pass_routes.py`: the node's answer

`PassService.passes(hours)` works in three steps:

1. pair the catalog with the store's latest sets (`match_catalog`);
2. ask the provider for windows over `[start, start + hours]`, with `start` the current minute, floored;
3. compute the gaps, and then `next_unobserved` from the *true* now.

Steps 1 and 2 are cached, 16 entries, keyed on `(unit, store version, start minute, hours)`. `_current_inputs` rebuilds the match and the provider only when the store's `version` moves. If any imager was skipped, `_compute` marks every gap low confidence.

The service publishes one bus message, `passes.updated`, on the node-scoped subject `node.<id>.passes.updated`, and its payload is only `{"reason", "elements_version"}`. `elements_changed` debounces a sync burst: the first change schedules one event a second later, and a change after that event is sent schedules another.

`pass_routes.py` maps this to HTTP (`docs/icd/passes-api.md`): 404 with no unit on `GET /api/passes/unit`, 409 with no unit on `GET /api/passes`, and 422 naming the field on a bad unit. It also answers 503 when an element set for a catalogued imager cannot be used, rather than answering without that imager.

*Easy to get wrong:* the `/api/passes` route is a plain `def`, so FastAPI runs it in a worker thread. That is why the cache is guarded by a `threading.Lock`, not an asyncio lock.

### 10. `sentinel/passes/tracks.py`: pictures, not answers

`ecef_track_m` returns Earth-fixed positions every 20 s for the console's globe, for at most 30 minutes. It refuses an interval more than 3 days from the element set's epoch, on either side (`_require_usable_span`). A pass answer keeps using an old set and flags it; a track has no field to carry a flag, and far from the epoch SGP4 returns finite positions that mean nothing. The check is written as differences (`start - epoch`), so a far-off epoch cannot overflow it.

### 11. `sentinel/passes/sync_adapter.py`: element sets ride the sync

`ElementRecords` implements the sync layer's `ReferenceRecords` protocol for element sets:

- Each set is offered under the item id `omm:<norad_id>`.
- Its deadline is the moment it goes stale (epoch plus 3 days), with ROUTINE consequence, so every urgent CDM is queued ahead of it (`tests/sync/test_modules_share_sync.py`).
- `ingest` hands fetched bytes to `ElementStore.add` and returns a named rejection code instead of raising.
- `sentinel/api/records.py` routes records between modules by that prefix, and `sentinel/sync` never changed to carry them (chapter 7).

A hub offers only the 38 catalog sets unless `SENTINEL_SYNC_ELEMENTS=all` (`_offered_elements` in `sentinel/api/app.py`). An edge loads no snapshot of its own and waits for sync, unless `SENTINEL_ELEMENTS` names one.

*Easy to get wrong:* nothing implements `ReferenceRecords` for the unit or its windows. That absence *is* layer 1 of ADR-010. Do not add one "for backup".

### 12. `sentinel/screening/`: geometry without a Pc

Read it in pipeline order:

- `orbit.py`, `Orbit`: one element set propagated by SGP4. The search stays in TEME, the frame SGP4 produces, because a rotation applied to both objects preserves the distance between them. Only the states written into a CDM are converted to GCRF. `OrbitUnusable` carries a code.
- `prefilter.py`, `may_approach`: the classic apogee/perigee filter. Two objects whose radial bands never come within the threshold cannot meet. Each band is widened by 25 km (`PAD_KM`), because SGP4's short-period terms carry the radius past the mean-element band.
- `search.py`, `find_close_approaches`: sample the relative state every 60 s. A bracket holds a minimum where the range rate goes from closing to opening. It is kept only if the range *could* dip below the threshold inside it: with the relative speed bounded by V over a step of length h, the lowest possible range is `(r_a + r_b - V*h) / 2`. Each kept bracket is refined with Brent's method on the range rate, to a microsecond.
- `screen.py`, `screen`: a primary that cannot be propagated refuses the whole screening (`ScreeningRefused`). A secondary that cannot is skipped, logged and named in the result.
- `derived_cdm.py`, `derived_cdm`: writes each approach as a CCSDS CDM with `ORIGINATOR = SENTINEL-SCREENING`, a demonstration comment, and no covariance. Each object block names its element set by the same sha256 the sync layer uses.
- `report.py`: the text report. A banner, and `Pc: refused — element sets have no covariance` on every approach line.

`sentinel/api/screening_routes.py` exposes `POST /api/screening` (`docs/icd/screening-api.md`). It ingests each approach as a DERIVED CDM through the ordinary conjunction path, so it shows up in the event list with its Pc refused.

*Easy to get wrong:* `.importlinter` forbids `sentinel.screening` from importing `sentinel.risk` or `sentinel.conjunction`. The refusal happens because the CDM is honest, not because screening tells the engine anything.

## Try it

Use a node of your own. A live demo runs on ports 8000 and 8001: never post to it, and never stop it. This chapter uses port 8123. The environment below makes an edge node that loads the vendored snapshot itself (an edge normally waits for sync). It also pins the node's clock to the snapshot's day, so the element sets are fresh whenever you run this.

```bash
export PATH=$HOME/.local/bin:$PATH
SENTINEL_ROLE=edge SENTINEL_NODE_ID=ch10-edge SENTINEL_VAR=/tmp/sentinel-ch10 SENTINEL_ELEMENTS=fixtures/omm/celestrak-resource-20260924.json SENTINEL_CLOCK=sim:2026-09-24T06:00:00Z,1 uv run sentinel serve --port 8123
```

The log should say `Element sets loaded ... accepted=167 rejected=0`. In a second terminal:

```bash
curl -s http://127.0.0.1:8123/api/passes/unit -w '\nHTTP %{http_code}\n'          # 404: no unit yet
curl -s 'http://127.0.0.1:8123/api/passes?hours=24' -w '\nHTTP %{http_code}\n'   # 409: nothing to predict for
curl -s -X PUT http://127.0.0.1:8123/api/passes/unit -H 'Content-Type: application/json' \
  -d '{"unit_id": "EX-UNIT-1", "lat_deg": 35.26, "lon_deg": -116.68, "alt_m": 700.0, "reaction_time_min": 30.0}'
ls -l /tmp/sentinel-ch10/unit.json                                                # -rw------- : mode 0600
```

That is the exercise unit from `docs/icd/passes-api.md`. The node logs `Unit set`, with no fields. Now ask for a day of windows and gaps, and print the parts worth reading:

```bash
curl -s 'http://127.0.0.1:8123/api/passes?hours=24' > /tmp/sentinel-ch10-passes.json
uv run python - <<'EOF'
import json
d = json.load(open("/tmp/sentinel-ch10-passes.json"))
print(d["provider"], "|", d["label"], "|", d["catalog"], "|", d["elements"])
for w in d["windows"][:6]:
    print(w["rise"][11:19], w["set"][11:19], f'{w["name"]:<24}', w["sensor"], "usable" if w["usable"] else "not usable",
          f'mask {w["mask_elevation_deg"]:.1f}', f'max {w["max_elevation_deg"]:.1f}', f'pad {w["pad_s"]:.0f}s')
for g in d["gaps"][:4]:
    print("gap", g["start"][11:19], "to", g["end"][11:19], round(g["duration_s"] / 60), "min", "LOW CONFIDENCE" if g["low_confidence"] else "")
print("next unobserved:", d["next_unobserved"])
EOF
```

What to look for:

- `provider` is `skyfield-local`, and `catalog` shows 38 imagers with an empty `skipped` list.
- The early windows are optical passes marked `not usable`: 06:00 UTC is night at the unit, so they observe nothing. They are listed anyway.
- If you ask within a minute or two of starting the node, the first window's rise can be *before* `start`. That is the overlap convention.
- Each window's `pad` is 60 s plus 30 s per day of age, and the mask differs by imager.
- The first gap starts at `start` and runs until the first usable window's padded start. `next_unobserved` starts at the node's current time, not at the floored minute.

Watch the one message the module publishes. Open the node's live stream in one terminal, and PUT the unit again with a different reaction time in another. Among the exercise's conjunction events, the stream shows `event: passes.updated` with `data: {"reason": "unit_set", "elements_version": 167}`. There is no id and there are no coordinates:

```bash
curl -sN http://127.0.0.1:8123/api/stream
```

Try the refusals. Each answer names the field and never echoes your value, and `GET /api/passes/unit` still returns the unit you stored before:

```bash
curl -s -X PUT http://127.0.0.1:8123/api/passes/unit -H 'Content-Type: application/json' -d '{"unit_id": "X", "lat_deg": 95.5, "lon_deg": 0}'
curl -s -X PUT http://127.0.0.1:8123/api/passes/unit -H 'Content-Type: application/json' -d '{"unit_id": "X", "lat_deg": 35, "lon_deg": 0, "alt_m": 12000}'
curl -s -X PUT http://127.0.0.1:8123/api/passes/unit -H 'Content-Type: application/json' -d '{"unit_id": "X", "lat_deg": 35, "lon_deg": 0, "grid": "11SNV"}'
curl -s 'http://127.0.0.1:8123/api/passes/tracks?norad_id=40115&start=2026-09-29T06:00:00Z&end=2026-09-29T06:10:00Z'
```

The last one is a track five days from the WORLDVIEW-3 epoch: 422, "the element set is stale over this interval".

**Staleness.** Stop the node (Ctrl-C) and start it again with `SENTINEL_CLOCK=sim:2026-10-01T06:00:00Z,1`, a week past the snapshot. The unit is still there: it was read back from `unit.json`. Ask for passes again. `elements.stale` is 38, every window has `stale: true` and a pad of about five minutes, every gap is `low_confidence`, and the log carries `Stale element set` warnings. The node still answers. Nothing on the screen claims more than the data supports.

**OPSEC on real processes.** The scenario starts a real hub and edge with their own nats-servers. It lets element sets reach the edge by sync, sets a unit at the edge, and captures everything the hub's server carries. The ports are picked free, so it does not touch the demo:

```bash
make tools                                # pinned nats-server and toxiproxy, sha256-verified
uv run python -m harness.run opsec
```

Expect ten `[PASS]` lines:

- Two show the setup worked: element sets reached the edge through sync, and the edge computed passes.
- Three are controls, which keep the negatives from being vacuous: a harmless canary *does* reach the hub, the edge *does* publish `passes.updated`, and the edge's own `unit.json` *does* hold the unit, at mode 0600.
- Four are the negatives. Nothing on the hub's wire matches the unit in any checked encoding. Canaries on `unit.>`, `passes.>` and `node.>` never arrive. The hub has no unit. No hub file holds one.
- The last says no process restarted.

The raw result lands in `harness/results/opsec.json`; the committed record is the OPSEC section of [`docs/ddil-results.md`](../ddil-results.md). `make opsec` runs the same scenario and then also rewrites that report when every scenario has a result, so prefer the command above while you are learning.

**Screening.** The make target screens WORLDVIEW-3 against the snapshot for the next 24 hours at 5 km:

```bash
make screen
```

The banner says `DEMONSTRATION MODE`. The `screened` line shows how many objects the apogee/perigee filter let through. At 5 km there is often nothing to report. Widen the threshold, pin the start to the snapshot's day, and write the approaches out as CDMs:

```bash
uv run sentinel screen --primary 40115 --start 2026-09-24T06:00:00Z --threshold-km 50 --out /tmp/sentinel-ch10-cdms
uv run sentinel assess /tmp/sentinel-ch10-cdms/SCREEN-*.cdm
```

With this snapshot and start there is one approach, so one file. Every approach line ends `Pc: refused — element sets have no covariance`. Open the `.cdm` file: `ORIGINATOR = SENTINEL-SCREENING`, the demonstration comments, GCRF states, and no covariance block. `sentinel assess` answers `REFUSED  NO_COVARIANCE`: that is the engine's ordinary gate, not a screening branch. Your node does the same over HTTP, and files the approach as a DERIVED event with `"refusal_reason": "NO_COVARIANCE"`:

```bash
curl -s -X POST http://127.0.0.1:8123/api/screening -H 'Content-Type: application/json' \
  -d '{"primary_norad_id": 40115, "threshold_km": 50}' | python3 -m json.tool
```

A primary the node has no element set for is 404 `UNKNOWN_PRIMARY`; on the command line it is `REFUSED` with exit code 2.

Finally, the tests behind this chapter:

```bash
uv run pytest -q tests/passes tests/conformance tests/ephemeris tests/adapters tests/screening
uv run lint-imports                       # includes the passes, ephemeris and screening contracts
```

## Design choices

**Compute at the edge, enforced four times** ([ADR-010](../system-design.md#adr-010--opsec-as-architecture-a-units-position-never-leaves-its-edge-node)). It buys a position that cannot leak through sync, because it never enters sync, and a pass answer that survives a cut link. It costs any hub-level picture of units: an aggregate view would need a reviewed release path. Rejected: computing at the hub and sending windows down, which puts the position on the link and the hub's disk. Also rejected: encrypting the position to the hub, where the hub still holds it, and relying on leaf permissions alone, which are one configuration line from a leak.

**Two providers, one contract, one oracle** ([ADR-011](../system-design.md#adr-011--two-pass-providers-behind-one-contract-held-to-one-conformance-suite)). It buys independence from one source of orbit data and one implementation, and makes the modularity claim testable. The suite paid for itself at once: one provider skipped an uncovered imager while the other raised, and raising became the contract. It costs two implementations and a suite to maintain, and the second provider's real feed is unproven (assumed schema). Rejected: converting inertial frames on ingest, which needs Earth-orientation data and adds a silent error source. Also rejected: trusting Skyfield's event finder as-is, and a bespoke table format when OEM exists.

**Every assumption errs towards observed time.** Wide fields of regard, SAR incidence read as off-nadir, windows refined on their outer side, pads widened with age, skipped imagers turning every gap low confidence: each one shortens gaps. It buys an answer whose error is in the safe direction for the unit, at the cost of under-reporting real gaps. The rule is in `sentinel/passes/catalog.py` and ADR-011's coverage rule.

**Keep answering with stale data, and say so.** A cut-off edge still needs an answer, so passes keep using old element sets with a growing pad and a `stale` flag (ADR-010, Consequence). The one place that refuses is the track, which has no way to carry a flag.

**Element sets are ordinary sync records** ([ADR-008](../system-design.md#adr-008--reference-data-application-level-priority-pull-not-transport-replication)). The module landed without a line of `sentinel/sync` changing. The cost is a round trip per record on a thin link, measured in ADR-008. That is why a hub offers only the 38 catalog sets by default.

**Screening writes a CDM the engine must refuse** ([ADR-002](../system-design.md#adr-002--two-screening-modes-explicitly-labeled)). It buys a refusal that holds by construction: there is no screening code path in the engine to get wrong. The cost is that demonstration mode has no risk number at all, and every output must say which mode it is. Rejected: one mode with caveats in a README, which never appear next to the number on screen.

## How it fails

- **A wrong unit** is 422 with `{"field", "reason"}`, and the stored unit is unchanged. The reason never contains the value (`tests/passes/test_unit_never_leaks.py` puts a distinctive position through every path and searches every log record, bus message and error for it).
- **A corrupt `unit.json`** at start-up is logged `Unit file unreadable` with the field. The node runs with no unit and answers 409: it does not guess.
- **No element sets yet**, for example an edge before its first sync, is still an answer: every imager is skipped as `missing`, and the whole interval is one low-confidence gap.
- **An element set for another object** under a catalogued NORAD id is skipped as `name_mismatch` and logged `Imager skipped`. Every gap turns low confidence, because a missing imager makes gaps look longer.
- **Stale element sets** widen the pad, set `stale`, mark gaps low confidence and log `Stale element set`. A track more than 3 days from the epoch is refused with a reason.
- **An unusable element set** (SGP4 cannot propagate it, or it is not in low Earth orbit) raises `ElementSetError`. The route logs `Pass computation refused` and answers 503, rather than answering with that imager quietly missing.
- **A provider without data** for an imager raises `ImagerNotCovered`. The conformance suite fails any provider that skips instead.
- **A bad ephemeris** is refused with a stable code: `REF_FRAME_NOT_EARTH_FIXED`, `TIME_SYSTEM_NOT_UTC`, `EPOCHS_NOT_INCREASING`, `STEP_TOO_COARSE`, or `SCHEMA_MISMATCH` from the Wayfinder adapter. The tabulated provider never extrapolates. When a table does not cover the interval, it logs `Ephemeris does not cover interval` and `Pass extends beyond searched ephemeris`, and leaves those passes out. Notice the direction: a pass left out makes the gap around it look longer, and nothing marks that gap low confidence. That is tolerable today only because this provider is not wired into a node. Handle it before wiring it in.
- **A bad element set over sync** is rejected with its code in the ingest result (`PARSE_ERROR`, `MISSING_FIELD`, `INVALID_FIELD`); a snapshot load logs `Element set rejected` for each.
- **Screening** refuses the whole run for an unknown or unusable primary (`UNKNOWN_PRIMARY`, `UNUSABLE_ELEMENTS`, `PROPAGATION_FAILED`). It skips and names an unusable secondary, and `Screening complete` logs the counts.

## Check yourself

1. A colleague proposes tightening the SAR entries in `imaging.toml` to their true off-nadir limits, "for accuracy". What happens to the gaps, and why does the module prefer the looser values?

   <details><summary>Answer</summary>

   A tighter limit raises the mask, shortens windows and lengthens gaps. The module is built so that every error shortens gaps, because telling a unit it is unobserved when it is observed is the dangerous direction. The looser values over-report observed time on purpose; the catalog docstring and each entry's `basis` say so.

   </details>

2. You write a third provider that logs a warning and skips any imager it has no table for. Which part of the repository catches it, and what would an operator have seen if nothing did?

   <details><summary>Answer</summary>

   `test_an_imager_absent_from_the_data_is_refused_not_silently_dropped` in `tests/conformance/test_pass_providers.py`, once the provider is added to `PROVIDER_FACTORIES`. Without it, the missing imager's passes would vanish, the gaps would grow, and the answer would carry no low-confidence flag, because the service marks gaps low confidence only for imagers it knows it skipped.

   </details>

3. `PassService.passes` floors `start` to the minute but computes `next_unobserved` from the unfloored now. Why both?

   <details><summary>Answer</summary>

   Flooring makes the expensive part (pairing and propagation) cacheable: every request in the same minute shares a key. But the reaction-time test must use the real now, or a gap already in progress would be credited with up to a minute that has already passed. So the cached report is reused and only step 3 is recomputed.

   </details>

4. An edge has been cut off for five days. What does its operator see in the pass answer, and why is the track endpoint stricter than the pass endpoint?

   <details><summary>Answer</summary>

   Windows with `stale: true` and pads over 200 s (60 s plus 30 s per day of age), `elements.stale` counting the stale sets, and every gap `low_confidence`, with `Stale element set` in the log. The node answers because a cut-off edge still needs one, and the flags carry the doubt. A track is a list of positions with no field for a flag, and SGP4 far from the epoch returns plausible-looking positions, so it refuses beyond 3 days.

   </details>

5. Someone adds `log.info("Unit set", lat=unit.lat_deg)` to `set_unit`. Which checks fail? Which ADR-010 layers still hold, so that the hub never sees the value?

   <details><summary>Answer</summary>

   `tests/passes/test_unit_never_leaks.py` and `test_nothing_logged_carries_the_unit` in `tests/passes/test_service.py` fail, and the OPSEC scenario fails its edge-log control. Logs are local, so the data-model, storage and transport layers still keep the value off the hub. The application layer is the one broken, and the tests exist because a log file is one more place to copy a position from.

   </details>

6. Why does screening write a CDM with no covariance instead of passing a "demonstration" flag that tells the engine to skip the Pc?

   <details><summary>Answer</summary>

   A flag is a code path in the engine that can be forgotten, mis-set or bypassed. A CDM with no covariance goes through the same ingest and the same `NO_COVARIANCE` gate as any other, so the refusal holds by construction. `.importlinter` also forbids screening from importing the engine, so no such flag could be passed.

   </details>

7. `skyfield_passes.py` reports rise at the end of its bracket that lies below the mask, so a rise can be up to a millisecond early and never late. Why that side?

   <details><summary>Answer</summary>

   An early rise widens the window, which can only shorten a gap. A late rise would leave a sliver of real observation outside every window, and that sliver would be counted as unobserved. The 1 s oracle found exactly such a sliver before the refinement existed.

   </details>

8. Why is an element set's sync deadline the moment it goes stale, with ROUTINE consequence?

   <details><summary>Answer</summary>

   The sync agent orders fetches by deadline and consequence (chapter 7). Stale time is when the set stops being trustworthy for pass timing, so it is the natural "needed by". ROUTINE keeps every urgent conjunction record ahead of public reference data on a thin link.

   </details>

## Where next

- [11. The AI assistant: a safety pattern](11-ai-assistant.md): the other module built on the node, and the event list your screened approach just joined.
- [7. Priority sync](07-priority-sync.md), for how `ElementRecords` is fetched, and [9. The DDIL harness](09-ddil-harness.md), for how `harness/scenarios.py` drives real processes.
- [13. Keeping it honest](13-guardrails-compliance-mbse.md): the import contracts and doc checks that hold this module's boundaries.
- Reference: [`docs/icd/passes-api.md`](../icd/passes-api.md), [`docs/icd/screening-api.md`](../icd/screening-api.md), [`docs/adapters/wayfinder.md`](../adapters/wayfinder.md), "The pass module and element sets over sync" in [`docs/technical-guide.md`](../technical-guide.md), and ADR-002, ADR-010 and ADR-011 in [`docs/system-design.md`](../system-design.md).
