# 5. The operator console

## What you will learn

- How the console under `web/` is laid out, and how any screen gets its data: `useResource` keyed by path, `useStream`, and one version counter.
- Why a Pc renders only through `PcValue`, which takes the whole assessment, how a source scan enforces that, and where the scan stops.
- Why the globe is CesiumJS with bundled imagery, no Cesium ion and no Cesium widgets, and how the node's Content-Security-Policy makes "never calls out" a browser rule.
- How the encounter plane and the dilution curve share one slider, and what they show about a diluted Pc.
- How the console stays honest when data is missing or hostile: `MARKING UNKNOWN`, read-only until told otherwise, error boundaries, and the tests that prove each.

## Why it exists

The console is where an operator decides, before the maneuver commit point, whether to act on a conjunction. Chapter 2 showed that the engine refuses rather than print a misleading Pc. The console can undo that work in a single line of JSX:

- a refused assessment shown as `0` or a blank reads as "no risk";
- a Pc shown without its method cannot be told apart from the originator's own number;
- a diluted Pc shown alone hides the fact that better data could make it larger.

The console also runs where the network is hostile or absent. It must work with no route to the internet, show attacker-controlled strings (an object name in an uploaded CDM, a peer operator's note) as plain text, never claim a classification it has not been told, and keep working when one panel receives a record it cannot draw.

## Concepts

### One page, served by its own node

The console is a single-page React app. `make web` builds it into `web/dist`, and the node serves that directory at `/` (chapter 4). Everything the page loads comes from the same origin:

```
 browser                                  the node (one origin)
 -------                                  ---------------------
 GET /                     ------------>  index.html
 GET /assets/index-*.js    ------------>  the React app (Vite build)
 GET /cesium/...           ------------>  Cesium workers, imagery tiles, CSS
 GET /api/node, /api/events/...  ----->   JSON (useResource)
 GET /api/stream           ------------>  server-sent events (useStream)
 POST /api/...             ------------>  operator writes (postJSON, putJSON, deleteJSON)

 Content-Security-Policy: default-src 'self'; connect-src 'self'; ...
 -> the browser itself refuses any request to another origin
```

ADR-009 is why: each node serves its own console from its own data, so an edge operator's screen does not depend on the link.

### Reads, events and one version counter

The console keeps no model of its own. It reads what the node says and reads it again when the node says something changed.

```
          /api/stream (SSE)
                |
                v
   useStream --onEvent--> App: setVersion(v + 1)     (every event, any kind,
                |                                     and "stream.opened")
                v
   version --> useResource("/api/events?scope=active", version)
           --> useResource("/api/events/<id>", version)
           --> useResource("/api/events/<id>/ops", version)   ... every panel
                |
                v
           refetch; keep the last good value of the same path while it loads
```

Two rules make this safe. A resource is keyed by its path: selecting a different event starts empty, so one event's data never appears under another's name. And a refetch that fails keeps the last good value of the same path, with the error beside it, so the screen never blanks on a transient failure.

### The PcValue contract

The engine's output contract (Tier 6 in `docs/risk-engine-design.md`) is that `pc` never travels without `method`, and that `dilution_flag` implies `pc_max`. The console keeps the same contract with one component. `PcValue` takes the whole `Assessment` object, never a number, so the rendering can always see:

```
 method = REFUSED  or pc = null   ->  "Pc refused"          (never a number, never 0)
 dilution_flag and pc_max        ->  "Pc 3.6×10⁻⁵  worst case 2.0×10⁻⁴"
 otherwise                       ->  "Pc 3.6×10⁻⁵"         (title: "method FOSTER_ESTES_2D")
```

The type system makes the right call easy. A source scan (`web/src/__tests__/pc-contract.test.tsx`) makes the wrong call fail CI.

### The encounter plane and the dilution curve

Here is only the geometry the two plots need. Near the time of closest approach (TCA) two satellites move past each other almost in straight lines. Look along their relative velocity and you see a flat picture, the *encounter plane* (also called the B-plane):

```
            encounter plane, seen along the relative velocity

                       .-~~~~~~~-.          3σ ellipse
                     .'  .-~~~-.  '.
                    :   (   *   )   :       * secondary's projected position
                     '.  '-...-'  .'          (the miss vector runs from the origin)
                       '-.......-'
                 \
          (O)     \ miss vector
       hard-body disk at the primary, radius HBR

   Pc = the share of the Gaussian around * that lies inside the disk
```

The ellipse is the combined position uncertainty of both objects (their covariances added and projected). The disk is their combined size. Chapter 2 derives the integral; here it is enough that Pc is "how much of the uncertainty cloud lands on the disk".

Now scale the covariance by a factor `k`. Variances scale by `k`, so each σ, and each ellipse radius, scales by `√k`. Pc as a function of `k` rises, peaks at `k*`, then falls as the cloud spreads too thin to put much mass anywhere:

```
  log Pc
    |            k*
    |           .*.
    |         .     .
    |       .         .        k = 1 (the data as given)
    |     .             .      |
    |   .                 .    o
    |  .                    .  |  .
    +---------------------------------------  log k
         tighter covariance       looser covariance

  k* < 1: the operating point sits right of the peak -> DILUTED.
  More uncertainty would lower this Pc, so a low value may mean ignorance, not safety.
```

The console draws both pictures side by side with one slider for `k`. Moving it grows the ellipse on the encounter plane and moves a line along the curve.

### An offline globe under a strict policy

CesiumJS is a WebGL globe. By default its `Viewer` takes its imagery from *Cesium ion*, a hosted service that needs an access token and a route to the internet, and builds its toolbar, timeline and pickers with Knockout, a library that compiles its bindings with `new Function`. Neither works here:

- a field network may have no route out, and the node's policy (`connect-src 'self'`) blocks any other origin anyway;
- `script-src 'self' 'wasm-unsafe-eval'` allows WebAssembly (Cesium's decoders need it) but blocks JavaScript `eval` and `new Function`.

So the console uses the bare `CesiumWidget`, which needs neither, and Cesium's own low-resolution NaturalEarthII imagery, copied into the build.

### Hostile strings

React escapes text by default: `{name}` becomes a text node, not markup. The danger is the few places that bypass that: `dangerouslySetInnerHTML`, `innerHTML`, `document.write`, a `javascript:` URL, an inline event handler. Strings from outside the console include object names and originators from any uploaded CDM, notes written on a peer node, AI answer text, server error details and element-set names. Each must arrive on screen as the literal characters, and nothing in it may run.

### Fail-safe defaults

Before `/api/node` answers, the console knows nothing about the node. Each default is the safe one:

| Unknown until the node answers | Default |
|---|---|
| Classification marking | the banner reads `MARKING UNKNOWN`, in grey, top and bottom |
| Whether the node is read-only | read-only: no triage buttons, no decision form, no unit edits |
| Which modules the node runs | no module tabs |
| A bookmarked tab for a module the node does not run | switch to Operations once the node answers or fails |

## Code walkthrough

Read the files in this order.

### `web/package.json`, `web/vite.config.ts`, `web/index.html`, `web/src/main.tsx`

**Purpose.** A Vite, React and TypeScript project. Scripts: `build` (`tsc -b && vite build`), `test` (`vitest run`), `typecheck`, `dev`. `vite.config.ts` does three things that matter:

- `viteStaticCopy` copies Cesium's `Workers`, `ThirdParty`, `Assets` and `Widgets` from the package into the build under `cesium/`, and `define` sets `CESIUM_BASE_URL` to `/cesium`, so Cesium resolves every file from the node itself;
- the dev server proxies `/api` to `http://127.0.0.1:8000`, which is what `make dev` relies on;
- `test` runs Vitest in jsdom.

`index.html` loads one module script from a file and has no inline script, which the CSP test checks. `main.tsx` renders `App` and imports `./features` only for its side effect: registering the module tabs.

**Easy to get wrong.** The dev proxy target is fixed at port 8000. With another node on 8000 (the live demo, for instance) `make dev` talks to that node.

### `web/src/api/types.ts`

**Purpose.** TypeScript mirrors of the node's JSON: `Assessment`, `EventSummary`, `EventDetail`, `Encounter`, `DilutionCurve`, `NodeInfo`, `OpsView`, `SyncStatus`, the assistant and pass types. They are written by hand, not generated from `docs/icd/openapi.json`. Two parts are checked mechanically: the `RefusalReason` union against the engine (`tests/test_refusal_reasons_mirrored.py`), and the stream kinds (below).

**Easy to get wrong.** A new server field compiles fine and simply never shows. Fields that only some nodes send are optional (`verification?`, `voice?`), and components treat an unknown value as a value, not an error: `VerificationChip` shows a state it has no text for by name.

### `web/src/api/client.ts`

**Purpose.** Every request the console makes.

- `getJSON` and `sendJSON` (`postJSON`, `putJSON`, `deleteJSON`) throw `HttpError` with the status and the body.
- `apiErrorMessage` turns FastAPI's `detail` into words, in its three shapes: a string, a validation list (a 422 on a query parameter), or an object with `reason` and `field` or `code` (the passes and screening interfaces).
- `useResource(path, version)` holds `{path, data, error, status}`. It refetches when the path or version changes and aborts the previous request. On failure it keeps the last data only when the path is the same. When the held path differs from the one asked for, it returns nothing at all.
- `useStream(onEvent)` opens an `EventSource` on `/api/stream` and adds a listener per kind in `kinds`. On open it reports `STREAM_OPENED`, because events sent while the stream was down are lost. On error it checks `readyState`: while the browser is retrying by itself (`CONNECTING`) it waits; once the browser has given up (`CLOSED`, which happens on an HTTP error such as a proxy's 502 during a restart) it logs `Event stream closed, reconnecting` and opens a new stream after `RECONNECT_MS`, the server's own `retry:` value.

**Easy to get wrong.** The `kinds` list. A kind missing from it is never delivered, because `EventSource` only dispatches named events to listeners for that name. `tests/docs/test_console_events.py` reads this list from the source and fails if it names a kind that `docs/icd/asyncapi.yaml` does not document. It cannot tell you that you forgot a new kind, so add it here when you add it to the ICD.

### `web/src/lib/`

- **`format.ts`.** `sci` (`3.6×10⁻⁵`, for display) and `sciPlain` (`3.6e-5`, for tables and axes); `metres` and `speed`, which switch to km and km/s; `countdown` (`T−10h 32m`, or `+3h 05m` once past); `dtg`, the military date-time group (`241907Z SEP 26`); and `REFUSAL_TEXT`, one plain sentence per refusal reason.
- **`marking.ts`.** `markingLevel` maps a marking to a banner colour by prefix, longest first so `TOP SECRET` never reads as `SECRET`. A marking that only *mentions* UNCLASSIFIED, or no marking, is `unknown`, and the unknown colour is grey, never unclassified green.
- **`useAction.ts`.** Wraps an operator's request: `busy`, the server's reason on failure, and a log call with a stable message and the HTTP status in the fields. A failed write is shown beside the control, never swallowed.
- **`log.ts`.** The repository's logging rule in the browser: `log.error({ status }, "Pass unit save failed")`, message constant, values in the fields.
- **`marks.ts`.** `diamond`, the SVG path used wherever a point must differ by shape as well as colour (a diluted update, a CARA 2D-invalid case).

### `web/src/App.tsx`

**Purpose.** The shell: marking banners, the top bar, tabs and the Operations layout (event list, globe, detail).

- `version` is the counter from the concepts section. `onStream` bumps it on every event and adds `cdm.accepted` and `cdm.rejected` events to the live feed. A streamed assessment in the feed goes through `PcValue` too (`FeedPc`).
- `useNodeClock` takes the offset between the node's `now` and the browser's clock each time `/api/node` is read, and ticks every second, so countdowns use the node's time rather than the browser's. The top bar adds `SIM` when `clock` is not `real`.
- `MARKING_UNKNOWN`, `readOnly={node?.read_only ?? true}` and `extensionTabs(node)` implement the fail-safe defaults.
- Every panel sits in its own `ErrorBoundary`. The event list resets when the list changes, the globe and detail when the selection changes.

**Easy to get wrong.** Two things follow from "bump on every event". First, on an edge the sync agent publishes `sync.progress` every cycle, so every visible resource is refetched every cycle; that is the price of having no client-side model. Second, the clock is only as fresh as the last read of `/api/node`, and `useNodeClock` assumes the node's time runs at wall speed in between. Under `SENTINEL_CLOCK=sim:...,60` the displayed clock runs at normal speed and jumps forward whenever `/api/node` is read again, which on a quiet standalone node may be only on reload.

### `web/src/extensions.tsx` and `web/src/features.tsx`

`registerTab` adds a tab with the module it belongs to; `extensionTabs(node)` returns only the tabs whose module is in `node.modules`. `features.tsx` registers Passes (`passes`), Sync (`sync`) and Assistant (`ai`, with `AiTierBadge` as its top-bar status). So a standalone node shows no Sync tab, and the read-only public node shows exactly what it runs.

### `web/src/components/PcValue.tsx`

**Purpose.** The only component allowed to render a probability of collision. `computed(a)` is true only when `method` is not `REFUSED` and `pc` is a number; anything else renders `Pc refused`, with the reason in the tooltip. `worstCase(a)` returns `pc_max` only when `dilution_flag` is set and `pc_max` exists, so a missing worst case is never printed as zero. `pcText` is the same contract as a string, for places that cannot hold markup, such as an SVG `<title>` in `HistorySpark`.

**The scan.** `web/src/__tests__/pc-contract.test.tsx` reads every source file (through `web/src/__tests__/fixtures/sources.ts`, which loads them as raw text and leaves the tests out) and finds calls to the console's number formatters, `sci(...)`, `sciPlain(...)`, `.toExponential(`, `.toPrecision(` and `.toFixed(`, applied to anything named like a Pc (`pc`, `_pc`, `pc_`). `PcValue.tsx` and `format.ts` own the rendering. Three files are allowed, each with a reason and an exact count:

- `DilutionCurve.tsx` (3): the Pc(k) curve's samples;
- `ValidationPanel.tsx` (4): this node's gate-off Pc beside CARA's published Pc;
- `EventDetail.tsx` (1): the originator's asserted Pc, labelled "theirs, not Sentinel's".

Because the counts are pinned, a fifth Pc in the Validation panel fails too.

**Easy to get wrong.** The scan reads names, not data flow, and it is "conservative ... to catch a regression, not to prove the rule", as its own comment says. One gap is live today. The node serves `GET /api/events/<id>/dilution-curve` for an event that the applicability gate refused (`CURVILINEAR_UNCERTAINTY`, `LOW_RELATIVE_VELOCITY`), marked `"model_applies": false`. `DilutionCurve` does not check that flag, so its caption prints `k=1 Pc ...` and `peak ... Pc ...` under a headline that says `Pc refused`. The scan's reason for allowing the curve ("served only when it returned a Pc") holds for `NO_COVARIANCE` but not for these reasons. Try-it step 5 shows the reply.

### `web/src/components/EventList.tsx` and `web/src/components/EventDetail.tsx`

**Purpose.** `EventList` shows each event with its countdown to the maneuver commit point, verification chip, band (`NO PC` for an unassessed event, plus a `worst` chip when dilution raises the band), names, `PcValue`, miss distance, and `DILUTED` or the refusal code.

`EventDetail` fetches three resources for the selected event: the detail, the encounter geometry and the dilution curve. It has two layouts:

- **Hub-asserted** (no CDM history on this node): the summary, `PcValue`, and a callout that says the Pc was asserted by the hub, not computed here, with the one-line `voice` summary. No plots, because no covariance has arrived.
- **Local**: `PcValue` large, the band, a refusal section (`REFUSAL_TEXT` plus the diagnostics that tripped the gate), a dilution callout that names `k*`, the operator panel, the plots, and provenance: inputs hash, engine version, the latest CDM's id and sha256, the originator's Pc labelled as theirs, the hard-body radius source, TCA refinement and admission warnings.

`log10k`, the slider's value, lives here and resets to 0 (that is, `k = 1`) whenever the selected event changes.

### `web/src/components/BPlane.tsx` and `web/src/components/DilutionCurve.tsx`

**`BPlane`** draws the encounter plane from `/api/events/<id>/encounter`: the miss vector `mu_m`, the ellipse axes `sigma_major_m` and `sigma_minor_m` with their angle, and the disk `hbr_m`. At slider value `log10k` it scales each ellipse radius by `√k`, and fades the fill as `1/k`, because the density at the centre falls that way. The frame is sized from `k = 1` and `k*`, so growth is visible rather than rescaled away. A disk smaller than 3.5 px is drawn larger and labelled `(enlarged)`.

**`DilutionCurve`** draws `log10 Pc` against `log10 k` from the engine's own samples (161 of them, spanning two decades beyond both `k = 1` and `k*`). It shades the dilution region to the right of `k*`, marks the operating point and the peak, and draws the slider line. `interpolatePc` reads the curve at the slider between samples, in log-log space, and the caption labels that value `(interpolated)`. The console never computes a Pc; it only reads between the engine's samples.

**Easy to get wrong.** The slider scales *variance* by `k`, so a slider at `k = 100` makes the ellipse 10 times larger, not 100.

### `web/src/components/Globe.tsx`

**Purpose.** Draws the two objects' arcs from `/api/events/<id>/trajectory`: Earth-fixed positions in metres, two-body propagation over ±20 minutes around TCA, visualization only (`sentinel/conjunction/trajectory.py` says how rough that is and why it does not matter). One effect creates a `CesiumWidget` with `TileMapServiceImageryProvider.fromUrl(buildModuleUrl("Assets/Textures/NaturalEarthII"))` as the base layer and a detached element as the credit container. A second effect replaces the arcs and labels when the trajectory changes, placing the two labels on opposite sides so they never overprint at TCA, and flies the camera to them.

**Easy to get wrong.** Reaching for the `Viewer` to get a timeline or a layer picker. Its UI compiles Knockout bindings with `new Function`, which the CSP blocks, so the globe would fail on the node while perhaps working in a development browser with no policy. `web/src/__tests__/csp.test.ts` reads the export list of `@cesium/widgets` and fails if any source imports one of those names from `cesium`, the Viewer and every other widget alike.

### The panels

- **`web/src/components/SyncPanel.tsx`** (`GET /api/sync`, Sync tab, nodes that run sync). On a hub: request counters. On an edge: the measured link, round trip and rate; the want-queue in fetch order (class, then earliest deadline), with each record's deadline, ETA and status, and `SUMMARY_ONLY` rows highlighted; and the arrivals, each with its sha256 check and verification. Chapter 7 explains the order.
- **`web/src/components/passes/PassesPanel.tsx`** (`/api/passes/unit`, `/api/passes?hours=24`, `/api/passes/catalog`). A 409 means no unit is set, and the headline asks for one. A failed refetch keeps the last good windows and says `Showing the last good result.` The footer `HONESTY_NOTE`, which says what the model leaves out, is rendered unconditionally, so it stays on screen whichever request fails. `UnitForm` is disabled on a read-only node. Chapter 10 covers windows and gaps.
- **`web/src/components/AssistantPanel.tsx`** (`/api/ai/status`, `/api/ai/ask`, `/api/ai/confirm`, `/api/ai/audit/verify`). It shows which tier routes and which phrases, and why; whether the audit chain verifies; each answer with its route, confidence and a `numbers grounded ✓` or `numbers not grounded` chip; a notice when a hosted answer was withheld; and, for a draft, a confirm form that records nothing until pressed. Chapter 11 covers the pattern.
- **`web/src/components/ValidationPanel.tsx`** (`GET /api/validation`, fetched once when the tab opens). This node's engine against NASA CARA: a log-log scatter with CARA's 2D-invalid cases drawn as diamonds, the confusion table of refusals against CARA's verdict, and every row. The numbers are computed on the node; the committed figures live in `docs/validation-report.md`.
- **`web/src/components/OpsPanel.tsx`** and **`web/src/components/LinkControl.tsx`**. Triage status with every concurrent value shown as `CONFLICT` until a person resolves it, the signed decision log with `REVIEW REQUIRED` on a decision made against a superseded CDM (chapter 8), and, on an edge, the `LINK` chip, which shows the *measured* state, never the preset chosen, with Toxiproxy presets when demo controls are on (chapter 6).

### `web/src/components/ErrorBoundary.tsx`, `Pending.tsx` and `Verification.tsx`

`ErrorBoundary` catches a render error in its children, logs `Panel render failed` with the panel label and component stack, and shows `<label> unavailable: <error>. The rest of the console is unaffected.` When its `resetKey` changes it tries again, so one malformed event does not blank the detail pane for every other event. `Pending` is what a panel shows before its data: `Loading…`, or `<what> unavailable: <reason>` once the request has failed. `VerificationChip` names HUB-ASSERTED, UPDATING, VERIFIED and MISMATCH, each with a tooltip, and shows any other state by its raw name.

**Easy to get wrong.** React error boundaries catch errors thrown while rendering, not errors in event handlers or promises. Those take the other paths: `useResource`'s `error`, and `useAction`'s `error`.

### The tests, `web/src/__tests__/`

| File | What it proves |
|---|---|
| `pcvalue.test.tsx`, `pc-contract.test.tsx` | the Pc contract, and the scan above |
| `csp.test.ts` | the source meets the node's CSP (below) |
| `hostile.test.tsx` | outside strings arrive as text (below) |
| `app.test.tsx` | `MARKING UNKNOWN` before the node answers, the marking's colour, a throwing tab contained, refetch when the stream reopens, a streamed Pc through `PcValue` |
| `client.test.tsx`, `stream.test.tsx` | error messages from each `detail` shape; `useResource` never shows one path's data under another; reconnect after an HTTP error, and no second stream while the browser retries |
| `degrade.test.tsx`, `error-boundary.test.tsx` | a failing endpoint says why instead of loading for ever; a panel that throws becomes a notice and recovers on a new key |
| `a11y.test.tsx` | controls have names; state is announced (`aria-expanded`, `aria-pressed`); colour is never the only signal |
| the rest | formatting, markings, logging, the feature tabs, the operator panel, the link control, the assistant and the pass views |

`csp.test.ts` reads the source as text and fails on: an external origin (`https://...`, except the SVG and XLink namespace names), a protocol-relative URL, `eval` or `Function(`, a string passed to `setTimeout`, an HTML sink, a `javascript:` URL, or an inline event handler in a string. It checks `index.html` for inline scripts, and it forbids importing any Cesium widget. Each rule is first shown to catch a bad example, so a green run means the rule ran.

`hostile.test.tsx` feeds five payloads (a `<script>` tag, an `<img onerror>`, an `<svg onload>`, an attribute breakout, a `javascript:` URL) through every place outside data reaches the screen: event names and ids, originators, message ids, warnings and diagnostics, a hub-asserted summary, an AI answer, an error caught by a boundary, the sync tables, a Pc tooltip, the pass timeline and catalog, and the live feed. `expectInert` then checks that each payload appears as literal text, that no active element exists (`script`, `img`, `iframe` and similar), that no attribute starts with `on`, that no link is a `javascript:` URL, and that `window.__pwned` was never set. Checking that the text *is* there matters: a component that dropped the string would also run no script, and would hide data from the operator.

The tests stub `fetch` with `mockApi` (`web/src/__tests__/fixtures/api.ts`), which rejects any request it was not told about, and replace `EventSource` with `FakeEventSource` (`web/src/__tests__/fixtures/stream.ts`), which a test opens, drops or fails by hand. jsdom has no WebGL, so tests mock `Globe`.

## Try it

Run these from the repository root.

**1. Install and run the console's tests.**

```bash
npm --prefix web ci --no-audit --no-fund
npm --prefix web run test -- --run
npm --prefix web run typecheck
```

The test script is already `vitest run`, so `-- --run` is harmless. Look for every test file passing and no failures; `typecheck` prints nothing after its header when the types hold.

**2. Run only the guards.**

```bash
npm --prefix web test -- pc-contract csp hostile
```

Vitest filters by file name. Three files run: the Pc contract, the CSP checks and the hostile-string checks.

**3. Break both guards on purpose.**

```bash
F=web/src/components/Scratch.tsx
cat > "$F" <<'EOF'
import { sciPlain } from "../lib/format";
export const Scratch = ({ pc }: { pc: number }) => <b>{sciPlain(pc)}</b>;
export const tiles = () => fetch("https://tiles.example.com/0/0/0.png");
EOF
npm --prefix web test -- pc-contract csp
rm "$F"
```

Two tests fail. The CSP test lists `"file": "src/components/Scratch.tsx"` with `"rule": "external origin"`. The contract test says `render these through PcValue (or pcText for plain text)` and names the same file. After `rm`, run step 2 again and both pass.

**4. See the console on its own node.** Build it, then start a node with a fast simulated clock on a free port:

```bash
make web
SENTINEL_VAR=/tmp/sentinel-ch5 SENTINEL_CLOCK=sim:now,60 uv run sentinel serve --port 8010
```

`curl -s -o /dev/null -w '%{http_code} %{content_type}\n' http://127.0.0.1:8010/` answers `200 text/html; charset=utf-8`. Open http://127.0.0.1:8010 in a browser and look for:

- for a moment on first load, the grey `MARKING UNKNOWN` banners and `no stream` in the top bar; then `UNCLASSIFIED // EXERCISE` in green, top and bottom, and `live`;
- `SIM` after the clock. Watch it for a minute: it advances one second per second, although `curl -s http://127.0.0.1:8010/api/node` shows the node's `now` running a minute per second. Reload the page and it jumps forward. That is the `useNodeClock` limit from the walkthrough;
- tabs Operations, Passes, Assistant, NASA reference and Validation, and no Sync tab and no `LINK` chip, because a standalone node runs no sync;
- in Operations, a `Pc refused` row with its code (`NO_COVARIANCE`, `INVALID_COVARIANCE`, ...) and a diluted row showing `worst` beside its Pc;
- on a diluted event, drag the slider under the curve: the ellipse on the encounter plane grows and fades, and the caption's `slider Pc≈` value is marked `(interpolated)`.

**5. See the gap in the scan.** With the node from step 4 still running:

```bash
curl -s http://127.0.0.1:8010/api/events/000029479-000054630-20230725T134006/dilution-curve | python3 -c '
import json, sys
d = json.load(sys.stdin)
print({k: v for k, v in d.items() if k not in ("log10_k", "pc")})'
```

This is a NASA reference event the gate refuses with `CURVILINEAR_UNCERTAINTY`. The reply has `'model_applies': False` and still carries `pc_at_k1` and `pc_max`. In the browser, open NASA reference and select any event refused with `CURVILINEAR_UNCERTAINTY`: the headline says `Pc refused`, and the curve's caption below it prints a Pc.

**6. Read an edge node, if the demo is running.** `make demo-local` runs a hub on 8000 and an edge on 8001. Only read from them:

```bash
curl -s http://127.0.0.1:8001/api/node | python3 -m json.tool
timeout 6 curl -sN http://127.0.0.1:8001/api/stream
```

The edge reports `"role": "edge"`, `"demo_controls": true` and `sync` among its modules, which is why its console has a Sync tab and a `LINK` chip with presets. The stream prints a `sync.progress` event every sync cycle even when nothing new has arrived. Each one bumps the console's version, so the edge console refetches what it shows every cycle; watch the browser's network panel on http://127.0.0.1:8001 to see it. (`timeout` ends the stream with status 124; that is expected.)

## Design choices

**One component renders every Pc, and a scan enforces it** (no ADR; the rule is in `CLAUDE.md`, and it extends the engine's Tier 6 contract in `docs/risk-engine-design.md`; the engine's own refusals are [ADR-003](../system-design.md#adr-003--reimplement-foster-estes-2d-pc-in-python-nasa-caras-published-cases-as-the-oracle)).
- *Buys:* a refusal is never a zero, a Pc never lacks its method, and a diluted Pc always has its worst case, on every screen at once. A new screen gets it by calling one component.
- *Costs:* a regex scan with a list of exceptions to maintain, pinned by count. It checks names, not data flow, so a Pc can still arrive by another route (step 5).
- *Alternatives:* trusting review, which misses a one-line `toExponential`; a branded "Pc" type, which would not stop a component from formatting the underlying number.

**CesiumJS with bundled imagery, no ion and no widgets, under `default-src 'self'`** (no ADR; the reasoning is in the `Globe.tsx` doc comment and the README; the console being on the node is [ADR-009](../system-design.md#adr-009--each-node-serves-its-own-console-node-local-events-never-cross-a-link)).
- *Buys:* the console works on a network with no route out, and the browser enforces that it never calls out. A mistake is blocked, not merely unlikely.
- *Costs:* a large JavaScript bundle, low-resolution imagery, and no timeline or layer picker. The policy is also weaker for styles than for scripts: `style-src` allows `'unsafe-inline'`.
- *Alternatives:* the full `Viewer` with `'unsafe-eval'`, which reopens JavaScript eval to any injected script; ion imagery or a CDN, which needs the internet.

**Refetch on every event, with resources keyed by path** (no ADR; step 8 of "Data flow of a CDM" in `docs/technical-guide.md`).
- *Buys:* the screen is always what the node holds, a lost event costs one refetch, and there is no second copy of server logic in the browser.
- *Costs:* many small requests: on an edge, a round of refetches every sync cycle. It is cheap only because the node is local.
- *Alternatives:* applying event payloads to a client-side store, which would duplicate the node's triage and verification rules in TypeScript and drift from them.

**Fail-safe defaults until the node answers** (no ADR; `App.tsx`, held by `app.test.tsx`).
- *Buys:* the console never asserts a classification, a write permission or a module it has not been told about.
- *Costs:* a moment of grey `MARKING UNKNOWN` and missing tabs on every load.
- *Alternative:* defaulting to the common case (`UNCLASSIFIED`, writable), which is wrong exactly when it matters.

**An error boundary around every panel** (no ADR; `ErrorBoundary.tsx`).
- *Buys:* one malformed record, or one module's bug, costs one panel, and the notice says which.
- *Costs:* it covers render errors only; asynchronous failures need `useResource` and `useAction` to report them.

**Hand-written types** (no ADR; `web/src/api/types.ts`).
- *Buys:* no code-generation step in the build, and types a person can read.
- *Costs:* drift is possible. Only refusal reasons and stream kinds are checked against their sources.

## How it fails

| What goes wrong | What the console does |
|---|---|
| `/api/node` has not answered, or fails | `MARKING UNKNOWN` in grey, read-only, no module tabs |
| An endpoint answers 404 or 5xx | `Pending` shows `<what> unavailable: <server's reason>` instead of loading for ever |
| A refetch fails after a success | the last good data of the same path stays, with the error beside it |
| The node closes a lagging stream | the browser reconnects after `retry: 3000`; `stream.opened` bumps the version and every panel refetches |
| A proxy answers the stream with 502 | the browser gives up (`CLOSED`); `useStream` logs `Event stream closed, reconnecting` and opens a new stream after 3 s |
| The stream is down | the top bar says `no stream`, in words and colour |
| A record a panel cannot draw | that panel shows `<label> unavailable: <error>`, logs `Panel render failed`, and tries again when what it shows changes (a new selection, a new list) |
| A verification state this console does not know | shown by its raw name, with a tooltip saying so |
| An object name containing `<script>` or `onerror=` | shown as literal text; nothing runs |
| A refused assessment | `Pc refused`, the reason, and its tripping values; never a number |
| A diluted Pc | the worst case beside it at every size, a `DILUTED` chip, and a callout naming `k*` |
| A read-only node | the write controls are not drawn; a write that reaches the node anyway gets 403, and `useAction` shows the node's reason |
| An operator write fails | the server's reason beside the control, and `Operator data write failed` in the browser log |
| A hosted AI answer states a number the tools did not produce | the answer is withheld, and the card says so and shows the facts |

Two gaps are worth knowing. The dilution curve prints a Pc for an event the applicability gate refused (the PcValue walkthrough). And `OpsPanel` renders nothing at all when its first read of `/api/events/<id>/ops` fails: it ignores the resource's error, so a broken operator-data read looks like a node without the module.

## Check yourself

1. Why does `PcValue` take an `Assessment` rather than `pc` and `method` as two props?

<details><summary>Answer</summary>

Two props can be passed separately, and one can be left out or taken from a different assessment. The whole object carries `method`, `pc`, `pc_max`, `dilution_flag` and `refusal_reason` together, so the component alone decides what is safe to show: "refused" for a refusal or a missing number, and the worst case whenever the flag is set. A caller cannot hand it a bare number, because the type does not accept one.
</details>

2. `pc-contract.test.tsx` passes. Does that prove no refused event shows a Pc anywhere?

<details><summary>Answer</summary>

No. The scan finds formatter calls applied to names that look like a Pc. It does not follow data. The dilution curve formats `curve.pc_at_k1`, an allowed exception, and the node serves that curve for events the gate refused (with `model_applies: false`), so a refused event can show a Pc there. The scan catches regressions of the common kind; it is not a proof.
</details>

3. You select event A, then event B, and B's detail request fails. What does the detail pane show, and why not A's data?

<details><summary>Answer</summary>

`Event unavailable: <reason>`. `useResource` holds the path its data belongs to. On failure it keeps the old data only when the path is unchanged, and when the held path differs from the requested one it returns nothing. So B starts empty and stays empty, and A's numbers can never appear under B's names.
</details>

4. The node closes a console's stream after it falls 256 events behind. Trace what happens in the browser until the screen is right.

<details><summary>Answer</summary>

The response ends, so `EventSource` fires `error` and moves to `CONNECTING`; `useStream` shows `no stream` and leaves the retry to the browser. After the server's `retry: 3000` the browser reconnects. `onopen` shows `live` and emits `stream.opened`. `App.onStream` bumps `version`, and every `useResource` keyed on it refetches, so the screen shows what the node holds now, including whatever the missed events announced.
</details>

5. Someone replaces `CesiumWidget` with `Viewer` to get the timeline. Which test fails, and what would have happened in the field?

<details><summary>Answer</summary>

`csp.test.ts` fails: `Viewer` is in `@cesium/widgets`' export list, and the test forbids importing any widget. In the field the node's `script-src` blocks `new Function`, which Knockout needs for the Viewer's UI, so the globe would fail on the node while perhaps working in a development browser with no CSP.
</details>

6. Why is the banner grey `MARKING UNKNOWN` before the node answers, instead of the usual `UNCLASSIFIED // EXERCISE`?

<details><summary>Answer</summary>

The banner is a security marking, not decoration. The console does not know the node's marking until `/api/node` answers, and a node may be marked SECRET. Showing UNCLASSIFIED by default would assert a classification nobody has stated, which invites mishandling of whatever is on screen. `markingLevel` also refuses to colour anything green that does not start with `UNCLASSIFIED`.
</details>

7. `hostile.test.tsx` checks that each payload appears in the page's text, not only that nothing ran. Why both?

<details><summary>Answer</summary>

A component that silently dropped the string would also run no script, and the test would pass while the operator lost data, such as an object's name. Requiring the literal text proves the string was rendered, and rendered as text rather than as markup.
</details>

8. You drag the slider from `k = 1` to `k = 100` on a diluted event. How much larger is the ellipse, and which way does the Pc go?

<details><summary>Answer</summary>

Ten times larger: `k` scales the covariance, so σ scales by `√k`. The event is diluted, so `k*` is below 1 and the operating point is already right of the peak. Going further right lowers the Pc: the cloud spreads thinner and less of it lands on the disk. That is the pathology the flag warns about, drawn.
</details>

## Where next

- [6. The bus and the link](06-bus-and-links.md): what the `LINK` chip measures and what the presets do to the real link.
- [7. Priority sync](07-priority-sync.md): the order the Sync panel shows, and what VERIFIED and HUB-ASSERTED mean.
- [8. Operator data: signed CRDTs](08-operator-data.md): `CONFLICT`, `RESOLUTION` and `REVIEW REQUIRED` in the operator panel.
- [10. Passes and screening](10-passes-and-screening.md) and [11. The AI assistant](11-ai-assistant.md): the modules behind the Passes and Assistant tabs.
- [2. The risk engine](02-risk-engine.md): the integral behind the encounter plane, and why `k*` decides dilution.
- Reference: the test layout in `docs/technical-guide.md`, the stream's events in `docs/icd/asyncapi.yaml`, and the measured engine results in `docs/validation-report.md`.
