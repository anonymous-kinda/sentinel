# Demo script: three minutes

A public walk-through of Sentinel on one machine: a hub and an edge, joined by a real leaf link that Toxiproxy shapes. Everything shown is exercise data and says so. Nothing here is operational.

Seven shots, in the order the exercise clock allows. Each lists the video time, the exact actions and what to say. The steps were run against `make demo-local` on the current code; the console labels quoted are the ones in `web/src/components/`.

## Before you record

Terminal A, from the repository root:

```bash
make install
SENTINEL_AI_CLOUD=1 make demo-local
```

Hosted AI is optional. To show the badge change between hosted tiers, also set `TYPESAFE_API_KEY` and `ANTHROPIC_API_KEY` in terminal A before `make demo-local`. Without them the assistant stays on local rules, and shot 5 shows the reason line changing instead (see there).

Terminal B, from the repository root. This writes a second wave of 16 exercise CDMs to disk; nothing is sent yet:

```bash
uv run sentinel exercise generate --out dist/wave2 --epoch now
```

Browser: the hub at `http://127.0.0.1:8000` on the left, the edge at `http://127.0.0.1:8001` on the right.

**The exercise clock.** Call T0 the moment terminal A prints `Sentinel demo is up`. The hub's scripted scenario then releases two more updates to the event EXSAT-1 × EX-DEB 412: the 4th CDM at T0+1:12 and the 5th at T0+3:36. Shot 2 catches the first live. Shot 3 cuts the link before the second, and shot 4 reconnects after it. That is what makes the offline decision stale.

| Video | Wall clock | Shot |
|---|---|---|
| 0:00–0:20 | T0+0:40 | 1. Console and globe |
| 0:20–0:50 | T0+1:00 | 2. The dilution slider |
| 0:50–1:30 | T0+1:30 | 3. DENIED: the edge keeps working |
| *(cut)* | wait to T0+3:40 | The hub receives the 5th update |
| 1:30–2:05 | T0+3:40 | 4. LIMITED: reconnect over a thin link |
| 2:05–2:25 | T0+4:30 | 5. The AI tier follows the link |
| 2:25–2:45 | T0+5:00 | 6. Screening refuses a Pc |
| 2:45–3:00 | T0+5:30 | 7. Passes: the unit stays on the edge |

## Shot 1 (0:00–0:20): console and globe

**Do.** Hub window, Operations tab. Click EXSAT-1 × EX-DEB 118 (RED). The globe draws both objects' tracks, on imagery bundled with the node.

**Say.** "This is Sentinel. The node serves its own console and makes no request beyond itself, so it runs with no internet. Warnings are ranked by when a decision is due, not by when they arrived. Everything here is exercise data, and labelled so."

## Shot 2 (0:20–0:50): the dilution slider

**Do.** Hub window. Click EXSAT-1 × EX-DEB 412. Drag the slider under the Pc-versus-covariance-scale plot slowly right, then back to the operating point. At T0+1:12 the event's 4th CDM arrives: the Pc falls, and the list shows DILUTED with a worst-case band.

**Say.** "This event's probability of collision is falling. That looks like good news. Drag the slider: as the uncertainty grows, the ellipse swells past the objects, and Pc climbs, peaks, then falls. A new update just arrived. Tracking got worse, the Pc went down, and Sentinel flags it DILUTED, with the worst case beside it."

## Shot 3 (0:50–1:30): DENIED, the edge keeps working

**Do.**

1. Edge window: click the LINK chip in the top bar, then **DENIED**. Within about 15 s the chip reads `LINK DENIED`. The chip shows what the edge measured, not the preset.
2. Edge: click EXSAT-1 × EX-DEB 412. Under "Triage and decisions", click **MANEUVER PLANNING**. Choose **MANEUVER**, type the rationale "Diluted; worst case RED", and click **Record decision**. The entry shows `✓ signed`.
3. Hub window: the same event. Click **WATCH**.
4. Terminal B: send the second wave to the hub.

```bash
for f in dist/wave2/*.cdm; do curl -s -o /dev/null --data-binary @"$f" http://127.0.0.1:8000/api/ingest/cdm; done
```

**Say.** "Now cut the forward node off. The link state is measured, not set. The edge keeps working: this operator records a signed decision on the diluted event. At the hub, someone else sets a different status on the same event. New warnings keep arriving at the hub."

**Cut.** Wait until the hub shows 5 updates on EX-DEB 412 (T0+3:36), then continue.

## Shot 4 (1:30–2:05): LIMITED, reconnect over a thin link

**Do.**

1. Edge: LINK chip, then **LIMITED** (about 8 kbit/s with 600 ms latency, on the real leaf link). The chip passes through DEGRADED and settles on `LINK LIMITED` in about 30 s; cut the wait.
2. Edge: **Sync** tab. Under "Queue - fetch order", the urgent rows are sorted by "to deadline", smallest first. "Arrivals" fills in with `sha256 ✓ · verified`.
3. Edge: **Operations**. The second-wave events appear marked `HUB-ASSERTED` before their full records arrive, then turn verified.
4. Edge: open the first EX-DEB 412 event. The status shows **CONFLICT** with both values, MANEUVER PLANNING from the edge and WATCH from the hub. The decision shows **REVIEW REQUIRED**.

**Say.** "Reconnect over a thin link. Every event crosses first as a small summary, marked hub-asserted. Full records follow, earliest maneuver deadline first, and the edge re-checks each one itself. Nothing was overwritten: both triage calls are kept, as a conflict for a person to resolve. And the offline decision is flagged review required, because the data it was made on has changed."

## Shot 5 (2:05–2:25): the AI tier follows the link

**Do.** Edge: **Assistant** tab. Point at the tier cards and "why this tier". Ask: "Why is 412 diluted?" The answer names the tool it used and the tier. Then set the LINK chip to **DENIED** and point at the tier again. Finish with **CONNECTED**.

What the screen shows:

| Link | With hosted keys | Without keys |
|---|---|---|
| CONNECTED | Badge `AI JEV+CLAUDE` | Badge `AI LOCAL`, "Jev not configured: local routing" |
| LIMITED | Badge `AI JEV`, "Link LIMITED: Jev routes (its answer is a few probabilities); prose stays local" | Badge `AI LOCAL`, "Jev not configured: local routing" |
| DENIED | Badge `AI LOCAL`, "Link DENIED: local routing only" | Badge `AI LOCAL`, "Link DENIED: local routing only" |

**Say.** "The assistant follows the link. On a thin link, only the routing model's small answer may cross. Cut off, it runs on local rules and templates. It never computes: validated code does. Any number it cannot trace to the tools is withheld."

## Shot 6 (2:25–2:45): screening refuses a Pc

**Do.** Terminal B:

```bash
curl -s -X POST -H 'content-type: application/json' -d '{"primary_norad_id": 41599, "hours": 24, "threshold_km": 5}' http://127.0.0.1:8000/api/screening
```

The reply says `"mode": "DEMONSTRATION"`, and each approach carries `"assessment": {"method": "REFUSED", "refusal_reason": "NO_COVARIANCE"}`. Then, in the hub window, open the new DERIVED event CARTOSAT-2C × CAS500-2: the Pc is refused for NO_COVARIANCE ([screening ICD](icd/screening-api.md)).

**Say.** "Public element sets tell you when two satellites pass close. They cannot support a probability, because they carry no uncertainty. Sentinel screens, files each approach as derived data, and the same engine refuses the Pc."

The window starts at the node's clock, so the approaches found depend on the day. On a day with none within 5 km, raise `threshold_km` (at most 50) or pick another primary. For a fixed result, the CLI takes a start time: `uv run sentinel screen --primary 41599 --hours 24 --start 2026-09-24T06:00:00Z` lists two approaches to CAS500-2, each ending "Pc: refused — element sets have no covariance".

## Shot 7 (2:45–3:00): Passes, the unit stays on the edge

**Do.** Edge: **Passes** tab. Click **Set unit** and enter Unit id `EX-UNIT-1`, Latitude `35.26`, Longitude `-116.68`, Altitude `700`, Reaction time `30`. Click **Save**. The tab shows the next unobserved window, the 24 h pass timeline and the imaging catalog. Then, in the hub window's address bar, open `http://127.0.0.1:8000/api/passes/unit`: it answers `404`, "no unit is set on this node".

**Say.** "For a ground unit: when can public imaging satellites see it? The edge computes that from public element sets its hub sent. A gap means 'not observed by catalogued imagers', never 'safe'. The unit's position never leaves this node. The hub has no unit at all, and a test on real processes watches the wire to prove it."

The evidence for that last sentence is `make opsec`, recorded in [the DDIL results](ddil-results.md#opsec). The pass API follows [the passes ICD](icd/passes-api.md).

## After recording

Stop terminal A with Ctrl-C. Each `make demo-local` starts fresh. Remove the second wave with `rm -rf dist/wave2`.

## Words to avoid

Do not call a gap "safe", a node "fielded", or the system "accredited" or "operational". Say "exercise data", "demonstration" and "not observed by catalogued imagers".
