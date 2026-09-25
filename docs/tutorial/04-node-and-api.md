# 4. The node and its API

## What you will learn

- How `create_app` assembles one node from settings, services, routes and background tasks, and why the same code runs as a hub, an edge or a standalone node.
- How an HTTP request travels: middleware, the app-wide write rules, the route, the service, and the event it publishes.
- How the live stream `/api/stream` works, and why a slow subscriber is disconnected rather than quietly dropped from.
- How configuration, the clock and logging are injected, so tests and the DDIL harness can control them.
- How the OpenAPI and AsyncAPI documents are kept equal to the code.

## Why it exists

An operator on a deployed node needs a working console on the host in front of them, even when the link to every other node is cut. The *node* is that host process. It holds the data, runs the engine, serves the API and the console, and publishes live events, all without asking anyone else.

Three further needs shape the code in this chapter:

- **One build, three roles.** What CI tests must be what runs in the field. A hub, an edge and a standalone laptop node are the same package with different environment variables.
- **One set of write rules.** A public read-only node must refuse every write, including routes added by modules written later. Oversized or malformed bodies must be refused, never crash the process.
- **Nothing lost in silence.** A console that falls behind the live feed is told so. Every failure is either a refusal the operator sees or a log line with a stable message someone can search for.

## Concepts

### A node, three roles

A node is one Python process (`sentinel serve`), plus its own `nats-server` when it runs with others. The role is configuration:

```
 standalone   in-process bus, no sync            laptop, single enclave, public read-only node
 hub          own nats-server; SyncServer        answers manifest, fetch and operator-data requests
 edge         own nats-server; SyncAgent         pulls from the hub named by SENTINEL_HUB_ID
```

Every role serves its own console from its own data (ADR-009). Chapters 6 to 8 cover what crosses the link between a hub and an edge. This chapter is about what happens inside one node.

### The composition root

A *composition root* is the one place where concrete objects are built and wired together. Everything else receives what it needs as arguments. In Sentinel that place is `sentinel/api/app.py`. The conjunction, operator-data and sync services never read environment variables, never pick a transport and never ask the wall clock. They are handed their settings, a `Bus` and a `Clock`. That is why a test can build a node with a frozen clock and an in-memory database in one line, and why the DDIL harness can start two real nodes whose clocks both begin on the day of the vendored element-set snapshot, so a run gives the same answer whatever day it runs.

```
create_app(settings?, clock?, bus?, start_background=True)
  |
  +- Settings.from_env()               only when no settings are passed
  +- build_node()                      synchronous, before the server starts
  |     clock     from SENTINEL_CLOCK      bus        LateBus around an in-process bus
  |     store     ConjunctionStore         conjunctions  ConjunctionService
  |     keys      load_identity            ops        OpsService
  |     link      LinkMonitor              elements   loaded from the role's snapshot
  +- FastAPI(lifespan, app-wide dependency refuse_writes_on_read_only)
  +- middleware: BodyLimit, then security_headers
  +- core routes: node, conjunctions, operator data, link and sync, stream
  +- registrars: assistant, passes, screening      (may fill node.extensions)
  +- static mount at "/" for the console           (last: it matches every path)

lifespan, when the server starts:
  swap in NATS -> build sync records -> SyncServer (hub) or SyncAgent (edge)
  -> load the NASA reference library -> start the exercise feeder -> "startup" hooks
  ... serve ...
  cancel background tasks -> "shutdown" hooks -> close the bus
```

### How a request travels

FastAPI sits on Starlette, which speaks ASGI: a request passes through a stack of middleware, is matched to a route, runs the route's dependencies, then runs the route. Sentinel uses each layer for one job.

```
 POST /api/events/E/decision  (body: JSON)
   |
   v
 security_headers   http middleware; on the way out it adds the CSP and friends
   v
 BodyLimit          ASGI middleware; 413 when Content-Length > 1 MB,
   |                and it counts streamed bytes so an unannounced body is cut off too
   v
 router             finds the APIRoute for the path
   v
 refuse_writes_on_read_only   app-wide dependency; 403 on a read-only node
   v
 decision()         json_object(): 422 unless the body is a JSON object
   v
 OpsService.append  signs the entry, stores it, publishes node.<id>.ops.changed
   |
   +--> 200 with the signed entry
   +--> every open /api/stream receives "event: ops.changed"
```

Because the security headers are the outermost layer, a 403 or 413 refusal carries the same Content-Security-Policy as a normal page.

### Server-sent events

*Server-sent events* (SSE) are a one-way stream over an ordinary HTTP response. The server keeps the response open and writes text blocks separated by a blank line:

```
retry: 3000

event: ops.changed
data: {"what": "annotation", "event_id": "1001-1002-20000101T000000"}

: keepalive
```

`retry:` tells the browser how long to wait before reconnecting. `event:` names the event, and the browser dispatches it to listeners for that name. A line starting with `:` is a comment; the node sends one every 15 s of silence so proxies do not close an idle connection. The browser's `EventSource` reconnects by itself after a dropped connection. That is most of what a console needs, over plain HTTP that passes through a proxy (the Caddy template sets `flush_interval -1` so events are not buffered).

SSE carries notifications, not the data itself. The console treats an event as "something changed, read it again" and refetches over the normal API. So a lost event costs a refresh, never a wrong screen, provided the console knows it may have missed something.

### Backpressure: close, don't drop

Each subscriber gets a bounded queue of 256 messages. A browser that stops reading (a laptop lid closed, a stalled proxy) fills its queue. There are three things a server can do then: grow the queue without limit (memory runs out on a small edge box), silently drop messages (the console shows stale data and never knows), or close the stream. Sentinel closes it and logs `Stream subscriber overflowed`. The browser reconnects, the console refetches everything it shows, and the operator's screen is correct again.

### Structured logging

A log line has a *message* and *fields*. The message is a constant string such as `Sync cycle failed`. You search and alert on it, so it must never contain a variable. The values go in fields: `hub_id=hub error=RequestTimeout`. Ten thousand failures are then one message with ten thousand field values, not ten thousand distinct messages. The rule has an OPSEC side too: the pass module logs `Unit set` with no fields at all, because a unit's position must never appear in a log.

### An injected clock

Every countdown, deadline and priority depends on "now". If code called `datetime.now()` directly, tests could not freeze time, the DDIL harness could not pin its nodes to a known day, and a demonstration could not run hours of scenario in minutes. So every service takes a `Clock`, and the process picks one from `SENTINEL_CLOCK`: `real`, `sim:<epoch>,<scale>` or `fixed:<instant>`.

## Code walkthrough

Read the files in this order.

### `sentinel/api/settings.py`

**Purpose.** One frozen dataclass, `Settings`, built from environment variables by `Settings.from_env`. Each field has a default that makes a laptop node work with no configuration.

| Variable | `Settings` field | Default | What reads it |
|---|---|---|---|
| `SENTINEL_NODE_ID` | `node_id` | `standalone` | subjects `node.<id>.>`, the signing-key file name, the default operator name |
| `SENTINEL_ROLE` | `role` | `standalone` | `lifespan`: `SyncServer` on a hub, `SyncAgent` on an edge |
| `SENTINEL_DB` | `db_path` | `:memory:` | the conjunction store and the operator data (SQLite) |
| `SENTINEL_MARKING` | `marking` | `UNCLASSIFIED // EXERCISE` | `/api/node`, the console banner, the AI tier policy |
| `SENTINEL_EXERCISE` | `exercise` | on | `_exercise_feeder` |
| `SENTINEL_LIBRARY` | `library` | on | `_load_library` (the NASA CARA reference events) |
| `SENTINEL_READ_ONLY` | `read_only` | off | `refuse_writes_on_read_only`; the assistant drafts nothing |
| `SENTINEL_DEMO_CONTROLS` | `demo_controls` | off | `POST /api/demo/link`, localhost only |
| `SENTINEL_WEB_DIST` | `web_dist` | the built console in a checkout, if present | the static mount at `/` |
| `SENTINEL_NATS_URL` | `nats_url` | unset (in-process bus) | `_connect_nats` |
| `SENTINEL_HUB_ID` | `hub_id` | unset | the edge's `SyncAgent` |
| `SENTINEL_SYNC_MODE` | `sync_mode` | `edf` | the edge's `SyncAgent`, which refuses anything but `edf` or `fifo` |
| `SENTINEL_SYNC_INTERVAL_S` | `sync_interval_s` | `2.0` | the edge's sync cycle |
| `SENTINEL_VAR` | `var_dir` | `var`, relative to the working directory | keys, `ai-audit.jsonl`, `unit.json` |
| `SENTINEL_TRUST_FILE` | `trust_file` | unset (trust only yourself) | `load_identity` |
| `SENTINEL_TOXIPROXY_API` | `toxiproxy_api` | unset | the link emulator used by demos and the harness |
| `SENTINEL_AI` | `ai` | on | `ai_routes.register` |
| `SENTINEL_AI_CLOUD` | `ai_cloud` | off | the operator's opt-in to hosted AI |
| `SENTINEL_ELEMENTS` | `elements_path` | unset (role default) | `_element_snapshot` |
| `SENTINEL_SYNC_ELEMENTS` | `sync_elements` | `catalog` | `_offered_elements`, which refuses anything but `catalog` or `all` |

Four more are read outside `Settings`: `SENTINEL_CLOCK` (`from_env` in `sentinel/clock.py`), `SENTINEL_LOG_FORMAT` and `SENTINEL_LOG_LEVEL` (`sentinel/obs.py`), and `SENTINEL_FIXTURES`, read once at import by `sentinel/validation/cara.py` and `sentinel/passes/element_store.py`. `sentinel serve` does not read the gitignored `.env` file; only `make ai-live-check`, `make ai-eval` and `make demo-local` load it (`sentinel/localenv.py`), and a variable already exported wins. The configuration reference in `docs/technical-guide.md` has the full table.

**Role validation.** `Settings.__post_init__` refuses a role that is not in `ROLES`. The comment there and `tests/api/test_node_role.py` say why: a mistyped `edg` used to start no sync while `/api/node` still reported a `sync` module, so a broken edge looked connected. Now the node refuses to start.

**Easy to get wrong.** Boolean flags go through `_flag`, which reads `1`, `true`, `yes` and `on` as true and *any other value* as false. Nothing validates them. `SENTINEL_READ_ONLY=enabled` therefore produces a writable node. Check `read_only` in `GET /api/node` after deploying a public node.

### `sentinel/clock.py`

**Purpose.** The only place the code asks what time it is. `Clock` is a `Protocol` with `now()`, `label` and `scale`. `RealClock` reads the wall clock. `SimClock` starts at an epoch and runs `scale` times faster, using `time.monotonic` so a wall-clock jump cannot move it. `FixedClock` is frozen, with `advance()` for tests. `from_spec` parses `SENTINEL_CLOCK`, and `from_env` is what `build_node` calls.

**Easy to get wrong.** Both `SimClock` and `FixedClock` refuse a naive datetime. `_parse_instant` treats a zone-less ISO string as UTC, so `sim:2026-09-24T00:00:00,60` is UTC, never local time. The label (`sim:...,60x`) travels to `/api/node`, and the console marks a non-real clock `SIM`, so a simulated clock can never pass for real time.

### `sentinel/obs.py`

**Purpose.** `get_logger(name)` returns a `StructuredLogger`. Its methods take the message positionally and the fields as keywords (`log.warning("Element snapshot missing", path=..., role=...)`). The fields ride on the standard `logging` record as `extra={"fields": ...}`. `configure_logging` installs one handler on the root logger: `JsonFormatter` (one JSON object per line, for journald or Elastic) when `SENTINEL_LOG_FORMAT=json`, otherwise `TextFormatter` (`key=value`). `log_level` picks the level: the `--log-level` flag, then `SENTINEL_LOG_LEVEL`, then INFO.

The policy is enforced by reading the source: `tests/test_logging_policy.py` parses every Python file under `sentinel/`, `scripts/`, `supplychain/` and `compliance/`, and fails on a log call whose message is an f-string, a `%` format, a concatenation or a variable.

**Easy to get wrong.** Two small things. `_log` passes `stacklevel=3`, so the record's file and line are the caller's rather than this wrapper's; add a wrapper layer and every log line points at the wrong place. And the two formats disagree on time: JSON writes `ts` as UTC ISO 8601, while the text format uses the standard `asctime`, which is local time with no zone. On a host not set to UTC, the text log and the JSON log of the same node show different clock times.

### `sentinel/api/app.py`

**Purpose.** The composition root and the core routes.

- **`Node`** is a dataclass holding everything a route or a module needs: settings, clock, bus, store, services, link monitor, element store, the sync agent or server, background tasks, and `extensions`. It is stored on `app.state.node`, which is how `refuse_writes_on_read_only` finds the settings.
- **`build_node`** does the synchronous work: it creates the clock, wraps the bus in a `LateBus`, opens the store, loads or creates this node's Ed25519 key under `SENTINEL_VAR`, loads the element snapshot for the role (`_load_elements`), and decides which element sets it offers edges (`_offered_elements`). It has side effects on disk, so tests pass a temporary `var_dir`.
- **`create_app`** builds the node, the FastAPI app, the middleware and the routes, then calls every registrar, then mounts the console.
- **`lifespan`** does the asynchronous work. `_connect_nats` swaps the in-process transport for NATS inside the `LateBus`, so services built earlier keep their reference. `_sync_records` puts every module's reference data behind one `CompositeRecords`. Then it starts `SyncServer` or `SyncAgent`, loads the library, starts the exercise feeder and runs `startup` hooks. `start_background=False` (used by tests and `scripts/export_openapi.py`) builds everything but starts no background task: no sync agent loop and no exercise feeder.
- **`node_info`** (`GET /api/node`) is what the console reads first: role, marking, clock label, `read_only`, and `modules`. `modules` lists `sync` only when `_runs_sync` finds a server or agent actually built, not when the role implies one.
- **`security_headers`** sets `CSP` and four other headers on every response, with `setdefault` so a route could override one. `default-src 'self'` turns "the console never calls out" into something the browser enforces (chapter 5).
- **`stream`** (`GET /api/stream`) subscribes to `subjects.local_all(node_id)`, which is `node.<id>.>`. `enqueue` puts each message on a queue of `STREAM_QUEUE_SLOTS`; on `QueueFull` it sets `overflowed` and logs `Stream subscriber overflowed` with the client, the slot count and the event kind. `events_out` writes `retry: 3000`, then loops: wait up to 15 s for a message (else send `: keepalive`), name the event by its `Sentinel-Kind` header, and replace a payload that is not JSON with `{"subject": ...}` so the `data:` line is always parseable. The `finally` block unsubscribes however the stream ends.

`Node.extensions` is a plain dict with a few agreed keys: `modules` (names reported by `/api/node`), `startup`, `shutdown` and `elements_changed` (lists of async hooks), and one entry per module service (`ai`, `passes`). The core never names a mission module; it reads these keys.

**Easy to get wrong.** Order. The static mount at `/` matches every path, so a route registered after it is never reached: it answers 404. That is why `_extension_registrars()` runs before the mount. The same ordering matters in `lifespan`: `_sync_records` is built there rather than in `build_node`, so the `elements_changed` hooks that registrars add are already present when the element records call them.

### `sentinel/api/bodies.py`

**Purpose.** Three rules, applied once to the whole app so a route added by a later module is covered without anyone remembering to do it.

- **Read-only.** `refuse_writes_on_read_only` is an app-wide dependency (passed to `FastAPI(dependencies=...)`). On a read-only node it refuses POST, PUT, PATCH and DELETE with 403, unless the matched endpoint carries the `read_only_safe` marker. One route has it: `POST /api/ai/ask`, a question that changes no node data.
- **Body size.** `BodyLimit` is ASGI middleware. It refuses a request whose `Content-Length` exceeds `MAX_BODY_BYTES` before reading anything. For a body with no length (chunked upload) it wraps `receive` and raises 413 as soon as the running total passes the limit, so an attacker cannot make a small edge box buffer a gigabyte.
- **JSON shape.** `json_object` returns a dict or raises 422 (`body is not JSON`, `body must be a JSON object`). `parse_json` also catches `RecursionError`, so `[[[[...` nested a hundred thousand deep is a 422, not a 500.

`tests/api/test_write_paths.py` enumerates every write route from `app.routes` and checks all three rules against each one. It also pins the set of `read_only_safe` routes, so exempting a new route is a visible change to a test.

**Easy to get wrong.** A route that reads its body with `await request.json()` skips the JSON rule and turns a malformed body into a 500; use `json_object` or `parse_json`. And remember that middleware runs before dependencies: an oversized POST to a read-only node gets 413, not 403.

### `sentinel/api/identity.py`

**Purpose.** `operator_of` returns the `X-Sentinel-Operator` header, or `operator@<node_id>` when it is absent. Every decision, note and annotation records that name as its author.

**Easy to get wrong.** Nothing authenticates the header. The node trusts its front proxy to set it, and the shipped Caddy template (`deploy/ansible/roles/caddy/templates/Caddyfile.j2`) neither sets it from a login nor strips one a client sent. On a writable node, any client can act under any name. The decision log's Ed25519 signature binds an entry to the *node's* key, not to a person. `SECURITY.md` lists this as known gap 1 (IA-2).

### `sentinel/api/extensions.py` and the route modules

**Purpose.** `REGISTRARS` lists the functions that add routes beyond the conjunction core. Each is `register(app, node)`.

- **`sentinel/api/ai_routes.py`.** With `SENTINEL_AI` off it registers only `GET /api/ai/status`, answering `{"enabled": false}`. Otherwise it builds a `ToolRegistry` over the node's services, loads a hosted provider only when its key variable is set (`_load_provider` imports the SDK lazily and logs `Hosted AI SDK not installed` if the extra is missing), and builds the `Assistant`. `_link_state` tells the tier policy which link to trust: an edge's measured hub link, or an assumed CONNECTED on a hub or standalone node, labelled as assumed. Routes: status, ask (marked `read_only_safe`), confirm, audit and audit verify. Chapter 11 explains the assistant itself.
- **`sentinel/api/pass_routes.py`.** Builds the `PassService` and registers an `elements_changed` hook so pass windows are recomputed when synced element sets arrive. Its routes have no docstrings on purpose: they are documented by hand in `docs/icd/passes-api.md` and tested against it. `PUT /api/passes/unit` reads its body with `parse_json` rather than `json_object`, because this interface answers every 422 as `{"field", "reason"}`, and never echoes the submitted value. Chapter 10 covers the module.
- **`sentinel/api/screening_routes.py`.** `POST /api/screening` validates its fields itself (`_request`, `_bounded`: unknown fields, booleans passed as numbers, NaN and out-of-range values are all 422), runs `screen` in a thread pool so the event loop keeps serving, then files each close approach as a DERIVED CDM through the ordinary ingest path. Those CDMs carry no covariance, so the engine refuses their Pc with `NO_COVARIANCE` (ADR-002).

**Easy to get wrong.** A registrar may put its module name in `node.extensions["modules"]`, and the console shows a tab only for a module the node reports. Forget that line and the routes work but the tab never appears. Screening adds no name because it has no tab.

### `sentinel/api/records.py`

**Purpose.** `sentinel/sync` takes one `ReferenceRecords`. `CompositeRecords` presents several modules as one, routing by item-id prefix: ids starting `omm:` go to the element-set records, everything else to the conjunction records. It lives here, in the assembly layer, so adding a module never edits `sentinel/sync` (chapter 7).

**Easy to get wrong.** `get` and `has` take a short sha256 prefix from the network. `_is_sha_prefix` accepts only 1 to 64 lowercase hex digits. Without it a value such as `%` or an empty string could act as a pattern that matches every record.

### `sentinel/api/apidoc.py` and `sentinel/api/validation_view.py`

`apidoc.py` holds OpenAPI metadata only: tags, the `KVN_BODY` and `json_body` declarations for routes that read their own body (FastAPI cannot infer a schema for those), and the documented ingest and SSE responses. Changing it changes the document, never behaviour.

`ValidationView.summary` re-runs NASA CARA's published operational cases through this node's engine and caches the result, so a node built with a different engine shows it in its own Validation tab. It runs on the first request, not at start-up, although the module and route docstrings say "at startup". The first `GET /api/validation` does the work; later ones are served from the cache.

### `sentinel/cli.py` and `sentinel/cli_ext.py`

**Purpose.** `sentinel` is the console script. `build_parser` defines the codec commands: `sentinel assess`, `sentinel cdm parse` and `sentinel cdm emit`. `_register_extensions` then calls `register` in `cli_ext.py`, which adds `sentinel serve`, `sentinel exercise generate` and `sentinel screen`. `main` maps outcomes to exit codes: 0 when a message was assessed (a refusal is still an assessment), 2 for `CdmRejected`, and 1 for `CdmParseError` or an I/O error.

`_serve` configures logging, then runs uvicorn with `log_config=None` (uvicorn's own lines go through Sentinel's handler) and `access_log=False` (requests are logged at the proxy in front). `uvicorn` and the API are imported inside `_serve`, so `sentinel assess` never loads the web stack.

**Easy to get wrong.** Exit code 1 covers more than usage and I/O errors. A file that is not KVN at all raises `CdmParseError` and exits 1, although the node quarantines the same bytes as `PARSE_ERROR` with a 422. Only admission failures after a successful parse exit 2.

### The interface documents

`docs/icd/openapi.json` is generated: `make openapi` runs `scripts/export_openapi.py`, which builds a node with every module registered and no background tasks, and writes canonical JSON. `tests/docs/test_openapi_current.py` fails when the committed file differs from a fresh export, so a route cannot change without its document changing in the same commit. Route docstrings become the operation descriptions, and `tests/api/test_route_docs.py` fails when a route raises a status its docstring does not name.

`docs/icd/asyncapi.yaml` cannot be generated, because nothing declares bus publishes the way FastAPI declares routes. It is written by hand and held to the code by `tests/docs/test_asyncapi.py`, which finds every node-local kind by reading the source at the `subjects.local` call sites. `make icd` regenerates the OpenAPI file and runs every drift test in `tests/docs`. `docs/icd/README.md` lists each document and the test that keeps it current.

## Try it

Run these from the repository root. The live demo owns ports 8000 and 8001, so this chapter uses 8010 and 8011, and keeps each node's state under `/tmp`.

**1. Start a standalone node.**

```bash
export PATH=$HOME/.local/bin:$PATH
SENTINEL_VAR=/tmp/sentinel-ch4 uv run sentinel serve --port 8010
```

The log shows `Element sets loaded` with `accepted=` and `rejected=` fields, then `Reference library loaded` with an `events=` count, then uvicorn's `Uvicorn running on http://127.0.0.1:8010`. Leave it running and use a second terminal.

**2. Ask the node who it is.**

```bash
curl -s http://127.0.0.1:8010/api/node | python3 -m json.tool
curl -s 'http://127.0.0.1:8010/api/events?scope=bogus'
```

Look for `"role": "standalone"`, `"clock": "real"`, `"read_only": false` and a `modules` list with `ai` and `passes` but no `sync`: this node builds neither a sync server nor an agent. The second call answers `{"detail":"scope must be active, past or all"}`.

**3. Ingest a CDM three ways.**

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
     --data-binary @fixtures/cara/SampleCDMs/AlfanoTestCase01.cdm http://127.0.0.1:8010/api/ingest/cdm
curl -s -o /dev/null -w 'HTTP %{http_code}\n' -X POST \
     --data-binary @fixtures/cara/SampleCDMs/AlfanoTestCase01.cdm http://127.0.0.1:8010/api/ingest/cdm
printf 'junk\n' | curl -s -w '\nHTTP %{http_code}\n' -X POST --data-binary @- http://127.0.0.1:8010/api/ingest/cdm
curl -s http://127.0.0.1:8010/api/quarantine | python3 -m json.tool
```

The first reply is 201, `"status": "accepted"`, with three `UNIT_LABEL_ANOMALY` warnings: incomplete input is accepted and says so. The second is 200: the same bytes have the same sha256, so nothing happens. The third is 422 with `"code": "PARSE_ERROR"`, and it appears in the quarantine list with its sha256 and source `api-upload`.

**4. Watch the live stream.** In a third terminal:

```bash
curl -sN http://127.0.0.1:8010/api/stream
```

You see `retry: 3000` at once. Now write to the node from the second terminal:

```bash
curl -s -X POST -d '{"field":"triage_status","value":"WATCH"}' \
     http://127.0.0.1:8010/api/events/1001-1002-20000101T000000/annotation
printf 'junk2\n' | curl -s -X POST --data-binary @- http://127.0.0.1:8010/api/ingest/cdm
```

The stream prints `event: ops.changed` with the event id, then `event: cdm.rejected` with the code and source. After 15 s of quiet it prints `: keepalive`.

**5. See who the node thinks you are.**

```bash
curl -s -X POST -H 'X-Sentinel-Operator: alice' -d '{"decision":"MONITOR","rationale":"tutorial"}' \
     http://127.0.0.1:8010/api/events/1001-1002-20000101T000000/decision
curl -s -X POST -d '{"text":"no header"}' http://127.0.0.1:8010/api/events/1001-1002-20000101T000000/note
```

The first entry has `"author": "alice"` and `"signature_valid": true`. The second has `"author": "operator@standalone"`. Nothing checked that you are alice: that is gap 1.

**6. Break the body rules.**

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST -d '[1,2]' \
     http://127.0.0.1:8010/api/events/1001-1002-20000101T000000/note
curl -s -w '\nHTTP %{http_code}\n' -X POST -d '{"decision":"PANIC"}' \
     http://127.0.0.1:8010/api/events/1001-1002-20000101T000000/decision
head -c 1100000 /dev/zero | tr '\0' x | curl -s -w '\nHTTP %{http_code}\n' -X POST --data-binary @- \
     http://127.0.0.1:8010/api/ingest/cdm
```

Expect 422 `body must be a JSON object`, 422 naming the allowed decisions, and 413 `a request body is at most 1 MB; a CDM is a few kilobytes`.

**7. Start a read-only node with JSON logs.**

```bash
SENTINEL_READ_ONLY=1 SENTINEL_NODE_ID=public SENTINEL_EXERCISE=0 SENTINEL_LOG_FORMAT=json \
SENTINEL_VAR=/tmp/sentinel-ch4-ro uv run sentinel serve --port 8011
```

Its log lines are JSON objects with `ts`, `level`, `logger`, `msg`, and the fields as keys. From another terminal:

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST \
     --data-binary @fixtures/cara/SampleCDMs/AlfanoTestCase01.cdm http://127.0.0.1:8011/api/ingest/cdm
curl -s -w '\nHTTP %{http_code}\n' -X DELETE http://127.0.0.1:8011/api/passes/unit
curl -s -X POST -d '{"text":"How is the link?"}' http://127.0.0.1:8011/api/ai/ask
curl -s -X POST -d '{"text":"/draft 25994 monitor"}' http://127.0.0.1:8011/api/ai/ask
head -c 1100000 /dev/zero | tr '\0' x | curl -s -o /dev/null -w 'HTTP %{http_code}\n' -X POST \
     --data-binary @- http://127.0.0.1:8011/api/ingest/cdm
```

Ingest and the unit delete answer 403 `this node is read-only`. The question is answered, because `ai_ask` is `read_only_safe`. The draft request comes back as `"status": "clarify"`, saying the node records no decisions and so drafts none. The oversized body gets 413, not 403: middleware ran first.

**8. Look at the interface the node publishes.**

```bash
curl -s http://127.0.0.1:8010/openapi.json | python3 -c 'import json,sys; print(sorted(json.load(sys.stdin)["paths"]))'
curl -s -D - -o /dev/null http://127.0.0.1:8010/api/health
```

The first lists every route, the passes and screening ones included. The second shows the `content-security-policy` header on an API reply. (Use `-D - -o /dev/null` rather than `curl -I`: a HEAD request gets 405, because the routes are GET only.) FastAPI's `/docs` page is also served, but it loads Swagger UI from a CDN with an inline script, and the node's own CSP blocks both, so in a browser it stays blank. Read `docs/icd/openapi.json` instead.

**9. Try the clocks.**

```bash
uv run python -c "
import time
from sentinel.clock import from_spec
c = from_spec('sim:2026-09-24T00:00:00Z,60')
a = c.now(); time.sleep(1); print(c.label, (c.now() - a).total_seconds())"
```

It prints the label `sim:2026-09-24T00:00:00+00:00,60x` and about 60 seconds of node time for one second of wall time. Restart the node on 8010 with `SENTINEL_CLOCK=sim:now,60` and `/api/node` reports that label, with `now` running a minute per second.

**10. Prove the documents match the code.**

```bash
make openapi
git status --short docs/icd/
uv run pytest -q tests/api/test_stream.py tests/api/test_write_paths.py tests/api/test_route_docs.py tests/docs
```

`make openapi` logs `OpenAPI document written` with a `paths=` count, and `git status` prints nothing: the export is byte-for-byte what is committed. The tests include the overflow test, which drives the stream at the ASGI level with a client that stops reading, and checks that the node logs the overflow and closes the stream.

**11. The CLI without a node.**

```bash
uv run sentinel --help
uv run sentinel assess fixtures/cara/SampleCDMs/AlfanoTestCase01.cdm; echo "exit $?"
```

The help lists `assess`, `cdm`, `serve`, `exercise` and `screen`. The assessment prints `REFUSED  LOW_RELATIVE_VELOCITY` with the tripping value in the diagnostics, and exits 0. Stop both nodes with Ctrl-C when you are done.

## Design choices

**One process per node, three roles by configuration** ([ADR-004](../system-design.md#adr-004--modular-monolith-with-an-internal-event-bus)).
- *Buys:* one signed bundle that runs air-gapped with nothing beyond its host; the code CI tests is the code each role runs.
- *Costs:* a node's modules deploy and scale together.
- *Rejected:* a service per module (orchestration an edge box does not have), and direct calls with no bus, which would close off moving a module out of process later.

**Each node serves its own console and its own stream** ([ADR-009](../system-design.md#adr-009--each-node-serves-its-own-console-node-local-events-never-cross-a-link)).
- *Buys:* the console keeps working when the link is down, and `/api/stream` carries only `node.<id>.>`, so an edge never shows a hub event it has not fetched and verified.
- *Costs:* every node is a web server to patch and harden, and each console sees only its own node's data.
- *Alternative it rules out:* one central web tier that edge operators reach over the link, which goes dark with the link.

**Write rules enforced once for the whole app** (no ADR; the rationale is in `sentinel/api/bodies.py`, and the proof is `tests/api/test_write_paths.py`).
- *Buys:* a route a new module adds is read-only-safe, size-limited and JSON-checked from its first commit.
- *Costs:* one body limit for every route, and an exemption needs the `read_only_safe` marker plus a change to the test's expected set.
- *Alternative:* checks inside each route, which a new route can forget.

**SSE, with close-on-overflow and refetch-on-open** (no ADR of its own; step 8 of "Data flow of a CDM" in `docs/technical-guide.md` describes it, and its node-local scope is [ADR-009](../system-design.md#adr-009--each-node-serves-its-own-console-node-local-events-never-cross-a-link)).
- *Buys:* plain HTTP through any proxy, reconnection built into the browser, and a one-way channel, which is all the console needs.
- *Costs:* events sent while a stream is down are lost, so the console must refetch on every open. The console also refetches its views on every event (chapter 5).
- *Alternatives:* WebSockets (two-way, with no reconnect built into the browser, for traffic that only flows one way), polling alone (latency, and load on the node), and silently dropping events for a slow client.

**Operator identity from a proxy header** (no ADR; [`SECURITY.md`](../../SECURITY.md), known gap 1).
- *Buys:* authentication stays with the front proxy, where a site's login system already lives.
- *Costs:* today nothing authenticates the header, so the author field can be forged on a writable node.
- *Deferred:* authentication inside the node. It is a documented gap (IA-2 in the POA&M), not a hidden one.

**Configuration from environment variables** (no ADR; `sentinel/api/settings.py`).
- *Buys:* systemd units, containers and the harness configure a node the same way; a bad role, element scope, sync mode or clock stops the node at start-up.
- *Costs:* flags are not validated, so a typo reads as off.
- *Alternative:* a configuration file, which would add a parser and a file to manage on every host.

**The HTTP interface document is generated, the bus document is written and tested** (no ADR; `docs/icd/README.md`).
- *Buys:* `openapi.json` cannot disagree with the routes, and `asyncapi.yaml` cannot miss a published kind.
- *Costs:* route docstrings are now interface text and are tested as such; the pass routes, documented by hand in `docs/icd/passes-api.md`, are exempt from the docstring checks.

## How it fails

| What goes wrong | What the node does | Where you see it |
|---|---|---|
| `SENTINEL_ROLE` misspelled | `ValueError` before the server starts | the process exits; `SENTINEL_ROLE must be one of hub, edge, standalone` |
| `SENTINEL_SYNC_ELEMENTS`, `SENTINEL_SYNC_MODE` or `SENTINEL_CLOCK` invalid | `ValueError` at build or start-up (sync mode only on an edge with a hub) | the process exits with the message |
| A boolean flag misspelled | read as off | nothing: check `/api/node` (see the settings walkthrough) |
| `nats-server` not up yet | 60 retries, 0.5 s apart, then the start-up fails | log `Waiting for nats-server` with `attempt` and `error` |
| NASA library or element snapshot missing | starts without them | log `Reference library missing` or `Element snapshot missing`, with the path |
| Link emulator unreachable | `/api/link` still answers, with `emulation: null` | log `Link emulator unreachable` |
| Hosted AI SDK not installed | the assistant uses the local tier | log `Hosted AI SDK not installed`; `/api/ai/status` |
| Write to a read-only node | 403 | `{"detail": "this node is read-only"}` |
| Body over 1 MB, announced or not | 413, without reading the rest | the reply |
| Body not JSON, not an object, or nested too deep | 422 | the reply |
| A CDM that is wrong | 422, quarantined, `cdm.rejected` published | `GET /api/quarantine`; the console's live feed |
| Unknown event | 404 on the detail and trajectory routes | the reply |
| Trajectory cannot be drawn (a state below the Earth's surface or beyond the 3 million km that ingest admits) | 422 | the reply; the globe shows nothing |
| A catalogued imager's element set is unusable | 503 on `GET /api/passes` | log `Pass computation refused` |
| A stream subscriber falls 256 events behind | the node closes that stream | log `Stream subscriber overflowed`; the console reconnects and refetches |
| Console not built | the API works; `/` answers 404 | `make web`, or set `SENTINEL_WEB_DIST` |

Three behaviours are worth knowing because they do not refuse:

- `GET /api/events/<unknown>/encounter` and `.../dilution-curve` answer 200 with `"available": false`, not 404. For an unknown id the encounter reply's reason is `no covariance or HBR`, which is misleading.
- A decision or note for an event id the node has never seen is accepted and signed, and an annotation for one is accepted too. The entry's `event_ref` then holds only the id, with no CDM hash, because there is no current CDM to bind it to.
- An edge whose `SENTINEL_HUB_ID` is unset starts no sync agent and does not report `sync`. It works as a node that never hears from a hub.

## Check yourself

1. You add a mission module with `POST /api/foo` that writes to the node's database. What must you do so a read-only node refuses it?

<details><summary>Answer</summary>

Nothing. `refuse_writes_on_read_only` is an app-wide dependency, so every POST, PUT, PATCH and DELETE is refused on a read-only node unless its endpoint is marked `read_only_safe`. `tests/api/test_write_paths.py` finds your route in `app.routes` and checks it. You only act when the route is a question that writes nothing: then you mark it and add it to `EXPECTED_READ_ONLY_SAFE`, which makes the exemption a reviewed change.
</details>

2. Why does a 2 MB POST to a read-only node answer 413 and not 403?

<details><summary>Answer</summary>

`BodyLimit` is middleware, and middleware runs before routing and dependencies. It sees the `Content-Length`, refuses at once, and the request never reaches `refuse_writes_on_read_only`. Both answers are refusals; the order only decides which one you get.
</details>

3. A colleague moves the `for register in _extension_registrars()` loop below the static mount. The tests for the core routes still pass. What broke, and why?

<details><summary>Answer</summary>

Every assistant, pass and screening route now answers 404 whenever a console is mounted. A mount at `/` matches every path, and Starlette tries routes in the order they were added, so routes added after it are never reached. The tests usually build the app with `web_dist=None`, which is why they can miss it.
</details>

4. A console's stream was closed for ten seconds while three CDMs arrived. How does its screen become correct, and why does the node not keep those events for it?

<details><summary>Answer</summary>

When the stream reopens, `useStream` emits `stream.opened`, and the console refetches everything it shows over the normal API. The node does not buffer because events are notifications, not data: the database already holds the truth, and a per-client buffer would mean unbounded memory for clients that never come back. The bounded queue plus "close, then refetch on open" gives a correct screen at a fixed memory cost.
</details>

5. An installer sets `SENTINEL_READ_ONLY=enabled` on the public node. What happens, and how would you catch it?

<details><summary>Answer</summary>

`_flag` reads only `1`, `true`, `yes` and `on` as true, so `enabled` is false and the node is writable. Nothing logs it. Catch it by checking `"read_only": true` in `GET /api/node` after deployment, or with a smoke test that expects 403 from a write.
</details>

6. Why is `log.info(f"Unit {unit.unit_id} set at {unit.lat_deg}")` wrong here, beyond style?

<details><summary>Answer</summary>

Three reasons. The message changes with every value, so no one can search or alert on it. `tests/test_logging_policy.py` fails on an f-string message. Worst, it writes a ground unit's position into the log, which ADR-010 forbids: the position never leaves the edge node, and logs get shipped. The real call is `log.info("Unit set")` with no fields.
</details>

7. Why is `openapi.json` generated while `asyncapi.yaml` is written by hand?

<details><summary>Answer</summary>

FastAPI knows every route, its parameters and its docstring, so the HTTP document can be exported from the running app and compared byte for byte. Nothing in Python declares "this code publishes kind X on the bus"; publishes are ordinary calls. So the bus document is written by hand, and `tests/docs/test_asyncapi.py` recovers the published kinds from the source, at the `subjects.local` call sites, and compares them with the document in both directions.
</details>

8. A decision in the log shows `"author": "alice"` and `"signature_valid": true`. What has been proven about who made it?

<details><summary>Answer</summary>

Only that the node holding that Ed25519 key recorded the entry and that it has not been altered since. The name came from the `X-Sentinel-Operator` header, which nothing authenticates. Whoever could reach the node could have sent it. That is gap 1 in `SECURITY.md`.
</details>

## Where next

- [5. The operator console](05-console.md): the other end of `/api/stream`, the PcValue contract, and the CSP seen from the browser.
- [6. The bus and the link](06-bus-and-links.md): `LateBus`, NATS leafnodes and the node-local subjects this chapter's stream relies on.
- [7. Priority sync](07-priority-sync.md): what `SyncServer` and `SyncAgent`, started in `lifespan`, do with `CompositeRecords`.
- [8. Operator data: signed CRDTs](08-operator-data.md): what `OpsService.append` signs and how it merges.
- [10. Passes and screening](10-passes-and-screening.md) and [11. The AI assistant](11-ai-assistant.md): the modules behind the registrars.
- Reference: the configuration reference and troubleshooting table in `docs/technical-guide.md`, the interface documents in `docs/icd/README.md`, and the known gaps in `SECURITY.md`.
