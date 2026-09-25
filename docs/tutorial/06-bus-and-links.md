# 6. The bus and the link

## What you will learn

- How Sentinel's modules talk through one `Bus` protocol, and why the same code runs on an in-memory bus in tests and on NATS on a deployed node.
- What a NATS leafnode is, and why each node runs its own `nats-server` that holds the link to the other node.
- Which subjects cross the hub-to-edge link and which never do, and which configuration line enforces each.
- How the edge *measures* CONNECTED, DEGRADED, LIMITED and DENIED from its own exchanges, and where that measurement can lag the real link.
- How the demo and the harness shape a real TCP link with Toxiproxy, and why those controls answer only on localhost.

## Why it exists

A forward node works over a link that is often denied, degraded, intermittent
or limited (DDIL). Three things must hold for its operator:

1. **The console keeps working when the link is gone.** If the console, the
   store and the engine needed the hub to talk to each other, the node would go
   dark exactly when the operator needs it.
2. **The console shows only what this node holds.** A hub event that has not
   yet been fetched and re-assessed at the edge must not appear as if it had.
3. **The operator sees what the link is doing, not what someone configured.**
   A "LIMITED" flag somebody forgot to reset is worse than no flag. The sync
   agent (chapter 7) and the AI tier policy (chapter 11) act on the same
   reading, so it has to be measured.

The bus answers the first two. The link monitor answers the third.

## Concepts

### Subjects, publish and request

Modules never call each other's objects across a boundary. They send messages
on **subjects**: dot-separated names such as `node.edge-alpha.cdm.rejected`.
A subscriber names a pattern. `*` matches exactly one token, and `>` matches
one or more trailing tokens:

```
pattern              subject                              match?
node.edge-alpha.>    node.edge-alpha.cdm.accepted.EX-1    yes
node.*               node.edge-alpha.cdm.rejected         no   (* is one token)
node.>               node                                 no   (> needs at least one more)
```

There are two ways to use a subject:

- **Publish and subscribe.** Fire and forget. Every matching subscriber gets a
  copy. Sentinel uses this for node-local events, such as "a CDM was accepted",
  which the console streams.
- **Request and reply.** One side asks and waits, with a timeout. One responder
  answers. Sync uses this for every hub-to-edge exchange.

### NATS for a newcomer

NATS is a small message server, one static binary. Clients connect to a server
over TCP and publish or subscribe. Core NATS keeps nothing: a message nobody is
subscribed to is simply dropped. Sentinel does not use JetStream, the
persistence layer (the Design choices section says why).

A **leafnode** connection joins two servers. One server, the leaf, dials out to
a listener on the other. After that, a client on either server can reach a
subscriber on the other, as if there were one server:

```
        edge host                                         hub host
 +--------------------------+                    +--------------------------+
 | sentinel (edge)          |                    | sentinel (hub)           |
 |    | client, 127.0.0.1   |                    |    | client, 127.0.0.1   |
 |    v                     |    leaf link       |    v                     |
 | nats-server (edge)  -----+--- TCP, dialled -->+ nats-server (hub)        |
 |   leafnodes.remotes      |    by the edge     |   leafnodes.listen       |
 +--------------------------+                    +--------------------------+
```

Three properties of leafnodes matter here:

- **Traffic crosses only where there is interest.** A server forwards a message
  over the leaf only if the other side has a matching subscription. When the
  hub's sync server subscribes to `sync.hub.manifest`, the edge's server learns
  of it. An edge request on that subject then crosses. The reply goes to the
  requester's private `_INBOX.<random>` subject, whose subscription the hub's
  server also knows about.
- **Local traffic stays local.** Each Sentinel process talks only to its own
  server on 127.0.0.1. If the leaf drops, the node's own bus is untouched, and
  the leaf reconnects by itself.
- **Permissions sit on the leaf.** The edge's remote can deny exporting
  (sending to the hub) and importing (receiving from the hub) by subject
  pattern. A denied subject stops at the edge's own server, whatever the
  application does.

When the leaf is down, the edge's server knows nobody serves
`sync.hub.manifest` and answers a request at once with "no responders". While
the link is a black hole that NATS has not yet noticed, a request just times
out. Both happen on a DDIL link. Neither is a bug.

### Node-scoped subjects

Every console event is published under `node.<node_id>.`, for example
`node.edge-alpha.cdm.accepted.<event_id>`. Two independent guards follow from
that (ADR-009). A console's event stream (`stream` in `sentinel/api/app.py`)
subscribes to `subjects.local_all(node_id)` and nothing else, so it never asks
for another node's events. And the edge's leaf denies `node.>` in both
directions, so they cannot cross even if something does ask. Without node
scoping, an edge console subscribed to `cdm.accepted.>` would receive the hub's
events before the edge had fetched and verified them.

```
crosses the leaf (request/reply, served by the hub)    never crosses
  sync.<hub_id>.manifest                                 node.>    console events, both ways
  sync.<hub_id>.fetch                                    unit.>    a ground unit's position
  ops.<hub_id>.exchange                                  passes.>  pass windows computed from it
  _INBOX.*  (the replies)
```

### Measuring the link

The edge learns about the link only through its own sync exchanges. Each
success gives a round-trip time and a byte count. Each failure is counted.
Two smoothed estimates come out of that, each an exponentially weighted moving
average (EWMA) with α = 0.3:

```
estimate  <-  0.3 * new sample + 0.7 * estimate
rate sample = bytes moved / seconds the exchange took     (only when bytes >= 2000)
```

The rate counts only exchanges of at least 2,000 bytes, because a small message
is all latency and says nothing about throughput. The state is then read in
this order, first match wins:

| State | Rule (defaults) |
|---|---|
| UNKNOWN | nothing tried yet |
| DENIED | never succeeded but has failed, or no success for more than 8 s and a failure since |
| LIMITED | measured rate under 4,000 bytes/s |
| DEGRADED | smoothed round trip of 1 s or more, or any failure since the last success |
| CONNECTED | otherwise |

The same estimates give an arrival time for a record of `n` bytes:
`eta = n / rate + rtt`. Chapter 7 uses it for admission control.

Two consequences follow from "measured", and both show up in Try it:

- **A reading needs traffic.** If nothing big crosses, the rate estimate does
  not move. A thin link carrying only small exchanges reads DEGRADED, from its
  round trip, not LIMITED.
- **The rate is not the link's capacity.** It is payload bytes over each
  round trip, latency included and before NATS compresses anything.
  `docs/ddil-results.md` states this next to the numbers it reports.

## Code walkthrough

Read the files in this order.

### `sentinel/bus/base.py`: the contract

`Bus` is a `typing.Protocol` with five methods: `publish`, `subscribe`,
`request`, `serve` and `close`. `Msg` is a frozen dataclass of subject, data
bytes and a string-to-string headers dict. A `Responder` returns
`(reply bytes, reply headers)`. Two exceptions carry the DDIL cases:
`RequestTimeout` (no reply in time) and `NoResponders` (nobody serves the
subject). Code above the bus catches these two, never a NATS type.

`subject_matches` implements the NATS wildcard rules in a few lines, so the
in-memory bus and the ICD tests (`tests/docs/test_asyncapi.py`) share one
definition.

*Easy to get wrong:* `>` must match at least one token. `node.>` does not
match `node`, and the function returns `False` for it, as NATS does.

### `sentinel/bus/subjects.py`: one namespace

Every subject is built here and nowhere else. `local(node_id, suffix)` makes
`node.<id>.<suffix>`, and `local_all(node_id)` makes the console's
`node.<id>.>`. `sync_manifest`, `sync_fetch` and `ops_exchange` make the three
cross-node subjects. `token` replaces any character other than a letter, a
digit, `-` or `_` with `_`, so an id can never add a token or a wildcard.

*Easy to get wrong:* building a subject with an f-string elsewhere. An event id
containing a dot would split into extra tokens, and `tests/docs/test_asyncapi.py`
finds node-local event kinds only at `subjects.local` call sites. A new kind
must go through `subjects.local` and get a channel in `docs/icd/asyncapi.yaml`,
or that test fails. The module docstring lists five node-local kinds; the ICD
is the complete list.

### `sentinel/bus/inprocess.py`: the bus in one process

`InProcessBus.publish` awaits every matching handler in turn. When `publish`
returns, every subscriber has seen the message, which makes tests
deterministic. A handler that raises is logged as `Bus handler failed`,
counted in `failures`, and does not stop delivery to the others.
`request` calls the first matching responder under `asyncio.wait_for` and turns
a timeout into `RequestTimeout`, and no responder into `NoResponders`.

`LateBus` is a small forwarder. Services are built synchronously in
`build_node` (`sentinel/api/app.py`), but NATS connects asynchronously at
startup. Every service holds the `LateBus`, and `_connect_nats` swaps its
`inner` transport for a `NatsBus` before anything subscribes.

*Easy to get wrong:* the two transports differ at the edges. In process,
`serve` stores one responder per subject, so serving a subject again
*replaces* the responder. The hostile-hub tests in chapter 7 rely on that to
put a tampering responder in front of the hub. On NATS, a second `serve` adds a
second member to the queue group, and either may answer. A responder that
raises propagates to the requester in process. On NATS, the requester gets an
empty reply with `Sentinel-Error: responder-failed`.

### `sentinel/bus/nats_bus.py`: the bus on a deployed node

`NatsBus.connect` connects to *this node's own* server, with unlimited
reconnects one second apart. `serve` subscribes with the queue group
`sentinel`. A responder that raises is logged as `Responder failed` and the
requester still gets an answer, so one bad request never kills the
subscription. `request` maps the NATS client's `NoRespondersError` and timeout
to the protocol's exceptions.

*Easy to get wrong:* the `connected` property says whether this process is
connected to its local server. It says nothing about the leaf. Link health
comes only from the link monitor below.

### `deploy/nats/hub.conf.tmpl` and `deploy/nats/edge.conf.tmpl`: the link

These two templates are the deployed shape of ADR-004 and ADR-009.
`harness/cluster.py` renders them (`render_nats`, `hub_nats_conf`,
`edge_nats_conf`) for the harness, the demo and the Compose stack, with
`string.Template.substitute`.

What each part does:

- **Both** listen for clients on 127.0.0.1 only, so no other host can reach a
  node's bus directly. A long `write_deadline` stops a slow link from being
  read as a slow consumer. `ping_interval: "5s"` with `ping_max: 3` finds a
  black-holed link in about 15 s instead of minutes.
- **The hub** has a `leafnodes` listener with `compression: s2_auto`, which
  chooses the S2 compression level from the round trip it measures.
  `no_advertise: true` stops the hub from gossiping its address, so a leaf that
  loses its configured path cannot quietly reconnect around it. The leaf
  handshake's authorization timeout is raised to 30 s so it completes over a
  thin link.
- **The edge** has one remote to the hub. `first_info_timeout: "20s"` lets the
  hub's first INFO message arrive over about 8 kbit/s. `deny_exports` holds
  `unit.>`, `passes.>` and `node.>`, and `deny_imports` holds `node.>`.

The "Findings from the DDIL harness" table in `docs/system-design.md` tells how
each of those non-default settings was found. `tests/compliance/test_deploy_conformance.py`
pins them and the deny lists.

*Easy to get wrong:* the `${LEAF_TLS}` and `${REMOTE_TLS}` placeholders. Every
renderer passes an empty string, so the leaf link is cleartext and has no peer
authentication. That is gap 2 in `SECURITY.md` (SC-8). Signed decision-log
entries still reject tampering (chapter 8), but nothing on the link is
confidential. A production rendering would put a `tls { ... }` block in both
places.

### `sentinel/linkstate/monitor.py`: measuring the link

`LinkMonitor` is a dataclass holding the thresholds (`denied_after_s`,
`slow_rtt_s`, `limited_bytes_per_s`, `alpha`) and the running estimates.
Callers report with `observe_success(rtt_s, nbytes, duration_s)` and
`observe_failure()`. `state` applies the table from Concepts, `snapshot()` is
what `GET /api/link` and the `link.state` event carry, and `eta_s(nbytes)`
predicts a transfer.

There is one monitor per node, built in `build_node`. Only the edge's sync
agent feeds it (chapter 7): after each operator-data exchange, each manifest
and each record fetch it calls `observe_success`, and when a cycle fails on
the link, `observe_failure`. A hub's monitor is never fed, so it reads
UNKNOWN.

*Easy to get wrong:* `observe_success` forgets both averages when the state
was DENIED. A link that returns after a denial is a new link. Without the
reset, a thin link coming back would read as the fast link that went away
(`tests/test_linkstate.py::test_recovery_forgets_the_fast_link_that_went_away`).
The same reset has a side effect, covered in How it fails.

### `sentinel/linkstate/toxiproxy.py` and the demo route

The demo and the harness put Toxiproxy, a TCP proxy that injects faults, on
the one connection that matters. It shapes the real TCP stream, so NATS, the
sync agent and the link monitor see what they would see on a bad radio link:

```
nats-server (edge) --leaf--> toxiproxy "leaf" proxy --> nats-server (hub) leaf listener
```

`PRESETS` maps each state name to Toxiproxy toxics: DEGRADED adds 600 ms of
latency and a 32 kB/s cap each way, LIMITED 600 ms and 1 kB/s, and DENIED a
`timeout` toxic with timeout 0 each way. `ToxiproxyControl.apply` deletes every
toxic on the `leaf` proxy, adds the preset's, and disables the proxy for
DENIED. The module's comment gives the intent: a denied radio link is a black
hole, not a polite TCP reset, so NATS must find it by its pings. What happens is
a little different. Disabling a Toxiproxy proxy also closes its live
connections, so the edge's server loses the leaf at once. In a probe, the leaf
was gone from the edge's `/leafz` at the first poll after applying DENIED. The
request already in flight timed out, and every later one failed with "no
responders". With the two timeout toxics alone and the proxy left enabled, the
leaf survived until the pings gave up, about 18 s. The DENIED preset therefore
does not exercise the 5 s ping settings; a real black hole would.

`sentinel/api/app.py` exposes two routes:

- `GET /api/link` returns `monitor` (the measurement) and, only with demo
  controls on, `emulation` (what Toxiproxy has been told).
- `POST /api/demo/link` applies a preset. It answers 403 unless
  `SENTINEL_DEMO_CONTROLS` is set *and* the client address is loopback, 503
  with no emulator, and 422 for an unknown preset. It publishes the node-local
  `link.emulation` event.

The console's LINK chip (`web/src/components/LinkControl.tsx`) calls that
route. In the Compose stack a browser request arrives from the Docker bridge
and is refused, so `harness/compose_link.py` (`make compose-link`) makes it
from inside the edge's container.

*Easy to get wrong:* `emulation.preset` and `monitor.state` are different
facts and can disagree. The preset is the cause and the monitor is the effect,
measured late. The console shows the monitor.

## Try it

**1. Subjects and wildcards.** No processes needed:

```bash
uv run python - <<'EOF'
from sentinel.bus import subject_matches, subjects
print(subjects.cdm_accepted("edge alpha", "EX/1.2"))
print(subjects.local("edge-alpha", "sync.progress"), subjects.sync_fetch("hub"))
print(subject_matches("node.>", "node.edge-alpha.cdm.rejected"),
      subject_matches("node.*", "node.edge-alpha.cdm.rejected"),
      subject_matches("node.>", "node"))
EOF
```

Look for `node.edge_alpha.cdm.accepted.EX_1_2`: the space, the slash and the
dot inside the ids became `_`, so each id is exactly one token. The last line
is `True False False`.

**2. The link monitor, fed by hand.**

```bash
uv run python - <<'EOF'
from sentinel.linkstate import LinkMonitor
m = LinkMonitor()
print("nothing tried yet ", m.state)
m.observe_success(1.4, 5_000, 1.4)          # a 5 kB record took 1.4 s
print("one 5 kB record   ", m.state, m.snapshot()["rate_bytes_per_s"], "B/s")
for _ in range(20):
    m.observe_success(0.002, 175, 0.002)    # fast again, but only small exchanges
print("20 small, fast    ", m.state, m.snapshot()["rtt_ms"], "ms")
m.observe_success(0.01, 50_000, 0.01)       # one big, fast transfer
print("one 50 kB transfer", m.state)
m.observe_failure()
print("one failure       ", m.state)
EOF
```

The sequence to look for is UNKNOWN, LIMITED, LIMITED, CONNECTED, DEGRADED.
The third line is the lesson. The round trip is back to a few milliseconds,
but no exchange of 2,000 bytes or more has crossed, so the rate estimate, and
with it LIMITED, has not moved.

**3. The running demo, read only.** If `make demo-local` is running, read the
edge's view. Never POST to ports 8000 or 8001: that would change the demo's
link.

```bash
curl -s http://127.0.0.1:8001/api/node | python3 -m json.tool
curl -s http://127.0.0.1:8001/api/link | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/link | python3 -m json.tool
```

On the edge, `role` is `edge`, `hub_id` is `hub`, `demo_controls` is `true`,
and `modules` includes `sync`. `/api/link` has both `monitor` and `emulation`.
On a healthy local link, `rtt_ms` is a few milliseconds and `exchanges` grows by
about two a second: one operator-data exchange and one manifest request per
cycle. On the hub, `monitor.state` is `UNKNOWN`, because no sync agent feeds
it, and there is no `emulation` key.

**4. Your own hub and edge over a shaped link.** This starts a private cluster
on free ports, with its own Toxiproxy, and leaves the demo alone. It needs
`make tools` and takes two to three minutes.

```bash
uv run python - <<'EOF'
import asyncio, datetime as dt, time
import nats
from harness.cluster import Cluster, http, wait_until
from harness.scenarios import post_cdm, scenario_cdms

def measured(c):
    m = http("GET", f"{c.edge}/api/link")["monitor"]
    return f"{m['state']:<9} rtt_ms={m['rtt_ms']} rate={m['rate_bytes_per_s']} failures={m['failures_in_row']}"

def preset(c, name):
    http("POST", f"{c.edge}/api/demo/link", {"preset": name})   # what the LINK chip does

async def hub_hears(c):
    """Subject families the hub's nats-server carries while the edge publishes
    one canary the leaf exports and one it must not."""
    hub = await nats.connect(f"nats://127.0.0.1:{c.ports['hub_client']}")
    edge = await nats.connect(f"nats://127.0.0.1:{c.ports['edge_client']}")
    heard = set()
    async def note(m):
        heard.add(m.subject.split(".")[0])
    await hub.subscribe(">", cb=note)
    await asyncio.sleep(1)
    await edge.publish("demo.canary", b"exported")
    await edge.publish("node.edge-alpha.canary", b"denied")
    await asyncio.sleep(4)
    await hub.close()
    await edge.close()
    return sorted(heard)

now = dt.datetime.now(dt.UTC)
first, _ = scenario_cdms(now)
later, _ = scenario_cdms(now + dt.timedelta(hours=6))
with Cluster(hub_exercise=False, sync_interval_s=1.0) as c:
    wait_until(c.leaf_connected, 20, what="leaf")
    for item in first:
        post_cdm(c.hub, item.kvn)
    time.sleep(8)
    print("compression: ", c.leaf_compression())
    print("hub heard:   ", asyncio.run(hub_hears(c)))
    print("CONNECTED    ", measured(c))
    for name in ("DEGRADED", "LIMITED"):
        preset(c, name)
        time.sleep(20)
        print(f"{name:<13}", measured(c))
    for item in later:                       # new records: something big must cross
        post_cdm(c.hub, item.kvn)
    time.sleep(40)
    print("LIMITED+data ", measured(c))
    preset(c, "DENIED")
    time.sleep(25)
    print("DENIED       ", measured(c))
    preset(c, "CONNECTED")
    time.sleep(15)
    print("CONNECTED    ", measured(c))
    try:
        http("POST", f"{c.hub}/api/demo/link", {"preset": "DENIED"})
    except Exception as exc:
        print("hub refuses: ", exc)
EOF
```

What to look for, line by line:

- `compression`: `s2_uncompressed` on both sides. On a local link the round
  trip is tiny, so `s2_auto` chooses not to compress.
- `hub heard`: `_INBOX`, `demo`, `ops` and `sync`, and never `node`. The
  exported canary crossed, which proves the capture works. The node-scoped
  canary and the edge's own `node.edge-alpha.*` events did not.
- `DEGRADED`: the round trip is above 1,000 ms, and the rate is still the old
  fast figure, because only small exchanges crossed.
- `LIMITED` (idle): still DEGRADED, for the same reason. The preset is
  LIMITED, but nothing big has crossed to show it.
- `LIMITED+data`: LIMITED, with a rate of hundreds of bytes a second. New CDMs
  gave the monitor transfers big enough to measure, but read How it fails for
  the route the reading took to get there.
- `DENIED`: `failures` climbing about once a second. The preset drops the leaf
  at once, so every request fails at once with "no responders".
- `CONNECTED`: a large rate again, measured afresh after the denial.
- The last line is `HTTP Error 403`. The hub was started without
  `SENTINEL_DEMO_CONTROLS`.

For measured behaviour on every link preset, read `docs/ddil-results.md`.
Chapter 9 runs the scenarios that produce it.

**5. The checks that hold this chapter to the code.**

```bash
uv run pytest -q tests/test_linkstate.py tests/docs/test_asyncapi.py tests/compliance/test_deploy_conformance.py
```

All pass. `tests/docs/test_asyncapi.py` also validates every message a hub and
an edge send against `docs/icd/asyncapi.yaml`.

## Design choices

**One `Bus` protocol, two transports (ADR-004).** It buys a modular monolith:
modules talk only through subjects, so tests run hub and edge in one process on
`InProcessBus` and a node runs the same code on NATS. `.importlinter` keeps
`bus` free of mission modules. It costs the transport differences described in
the walkthrough, which tests must not depend on by accident. Rejected: direct
function calls, which would rule out splitting the modules across processes
later. See [ADR-004](../system-design.md#adr-004--modular-monolith-with-an-internal-event-bus).

**Each node runs its own `nats-server`, and the server holds the link
(ADR-004).** It buys a node whose bus never depends on the link: the DENIED
scenario measures the edge console while the link is cut. It costs a second
process to ship, configure and harden, which ADR-004 states plainly rather than
embedding a server. Rejected: Kafka (a JVM and a quorum, no disconnected-leaf
story), Redpanda (lighter, but no comparable leaf model) and plain MQTT (no
request/reply, no leaf model).

**Core NATS, no JetStream (ADR-004, ADR-008).** It buys one ordering to
explain: sync decides the order by mission priority (chapter 7), and operator
data is a CRDT that does its own store-and-forward (chapter 8). It costs
writing and testing a sync protocol instead of configuring a mirror. Rejected:
a JetStream mirror, which delivers in stream (FIFO) order, the baseline the
LIMITED scenario measures against. See
[ADR-008](../system-design.md#adr-008--reference-data-application-level-priority-pull-not-transport-replication).

**Node-scoped subjects, denied both ways at the leaf (ADR-009).** It buys a
console that never shows a hub event before the edge has fetched and verified
it, and that keeps working with the hub unreachable. It costs every node
serving its own web app, and each console seeing only its own node. Rejected:
shared subjects such as `cdm.accepted.>`, which leafnode interest would carry
across. See [ADR-009](../system-design.md#adr-009--each-node-serves-its-own-console-node-local-events-never-cross-a-link).

**Transport permissions as an OPSEC layer (ADR-010).** Denying `unit.>` and
`passes.>` at the leaf means an application bug that publishes a unit's
position still stops at the edge's own server. It costs a configuration line
that must stay right, so a compliance test pins it. It is the fourth of four
layers, never the only one. See
[ADR-010](../system-design.md#adr-010--opsec-as-architecture-a-units-position-never-leaves-its-edge-node).

**Link state is measured, never configured.** It buys an operator reading, and
admission-control and AI-tier decisions, that follow the real link. It costs
lag: the monitor needs traffic to notice a change, and fixed thresholds
(8 s, 1 s, 4,000 B/s) that suit a satellite-class link but are not tuned per
deployment. The technical guide's "Link state is measured" section is the
reference. Rejected: an operator-set link flag.

**Toxiproxy on the leaf, and NATS tuned to what it found.** Shaping the real
TCP stream buys a test in which every layer above it runs as deployed, in WSL,
on a laptop or in CI. It found four NATS defaults that assume a LAN (the
"Findings from the DDIL harness" section of `docs/system-design.md`). The
longer handshake timeouts make a handshake that will never finish fail later,
and the faster pings spend a little of a thin link. The emulation costs
packet-level realism: TCP retransmits hide loss, so real packet loss is
`tc netem`'s job, as the module docstring says.

## How it fails

- **The link is cut.** On a real black hole, requests time out until NATS
  pings detect the dead leaf, in about 15 s. (The DENIED preset closes the
  connection, so there the leaf drops at once.) After that, requests fail at
  once with `NoResponders`. The sync agent counts each failure, the monitor
  reads DENIED after 8 s without a success, and the `link.state` event tells
  the console. The node's own bus, store and API are unaffected. The DENIED
  scenario in `docs/ddil-results.md` asserts that.
- **The link turns thin with no denial in between.** Watch for this one. The
  rate estimate still holds the old fast figure. Averaging alone would need
  about twenty large transfers to bring a LAN-class estimate under
  4,000 B/s (0.7 to the twentieth power is about 0.001). What happens instead
  is this. Request timeouts are sized from the rate (chapter 7), so they are
  short. The first record over the thin link times out, and the monitor reads
  DEGRADED. If more than 8 s pass between successes, it reads DENIED, and the
  next success clears the averages and measures the thin link afresh as
  LIMITED. So an operator can see a brief DENIED that was really a sudden
  slowdown. Try it 4 samples too rarely to catch it. Polled every half second
  during its `LIMITED+data` phase, one run read DEGRADED, then a
  `RequestTimeout` in `last_cycle` of `GET /api/sync`, DENIED for about a
  second, and then LIMITED.
- **The link recovers while idle.** LIMITED persists until a transfer of 2,000
  bytes or more crosses (Try it 2). With nothing to sync, the chip can read
  LIMITED on a good link. The next CDM corrects it.
- **A subscriber raises.** `InProcessBus` logs `Bus handler failed` with the
  pattern and subject, and delivers to the rest. On NATS, a responder that
  raises is logged as `Responder failed` and answers
  `Sentinel-Error: responder-failed`, so the requester is never left waiting.
- **`nats-server` is not running.** The node waits at startup and does not
  answer `/api/health`. About once a second, the NATS client logs
  `nats: encountered error` with a "connection refused" traceback. When the
  server appears, the node finishes starting within a second or so. Nothing
  falls back to the in-process bus. Read `_connect_nats` with care. It retries
  60 times and logs `Waiting for nats-server`, but `NatsBus.connect` asks for
  unlimited reconnects, and with that option the NATS client keeps retrying
  inside its first `connect` call. That loop never gets an exception to count.
- **The link emulator is misused or missing.** A remote caller, or a node
  without demo controls, gets 403 from `POST /api/demo/link`. An unreachable
  Toxiproxy turns `emulation` into `null` in `GET /api/link`, logged as
  `Link emulator unreachable`, rather than failing the route.
- **A subject that must not cross.** It stops at the edge's server by
  `deny_exports`, whatever the code publishes. If the deny list is edited,
  `tests/compliance/test_deploy_conformance.py` fails, and if the ICD and the
  config disagree, `tests/docs/test_asyncapi.py` fails. What is allowed to
  cross is readable by anyone on the path: the leaf is cleartext and
  unauthenticated (`SECURITY.md`, gap 2).

## Check yourself

1. The edge console subscribes to `node.edge-alpha.>`. What would an operator
   see if the edge's `deny_imports` line were deleted, and which ADR's promise
   would break?

   <details><summary>Answer</summary>

   Nothing would change at first, because the edge console subscribes only to
   its own node's subjects. The deny is the second guard. If the console, or
   any future subscriber, used a wider pattern such as `node.>`, the hub's
   `cdm.accepted` events would cross, and the edge would show hub events it had
   not fetched and verified. That breaks ADR-009's HUB_ASSERTED/VERIFIED
   distinction. The two guards are independent, so either one alone still
   holds.
   </details>

2. The Toxiproxy preset says LIMITED, and `GET /api/link` says DEGRADED. Which
   is wrong?

   <details><summary>Answer</summary>

   Neither. The preset is what the link was told to do. The monitor is what
   the edge has measured. Until a transfer of at least 2,000 bytes crosses,
   there is no new rate sample, so the monitor can only see the long round
   trip, which is DEGRADED. The console shows the measurement on purpose.
   </details>

3. Why does the Sentinel process connect to `127.0.0.1` rather than to the
   hub's address?

   <details><summary>Answer</summary>

   So the node's bus never depends on the link. The console, store, engine and
   ops service all talk through the local server, which keeps working when the
   leaf is down. The server, not the application, holds the link and reconnects
   it. `NatsBus.connected` therefore says nothing about the hub.
   </details>

4. `observe_success` throws away the averages after a denial. What would the
   operator and the sync agent get wrong without that, and what does the reset
   cost?

   <details><summary>Answer</summary>

   Without it, a link coming back thin after a denial would carry the old fast
   estimates. The chip would read CONNECTED, and admission control would
   predict arrival times far too short. The reset is tied to DENIED, and that
   is its cost. A link that slows suddenly, with no denial, carries the stale
   estimate until short timeouts push the monitor through a brief DENIED.
   </details>

5. Why does the rate estimate ignore exchanges smaller than 2,000 bytes?

   <details><summary>Answer</summary>

   A small exchange takes almost all its time in latency. At 600 ms each way,
   a 200-byte reply "moves" under 200 B/s whatever the bandwidth, and the link
   would read LIMITED when it is only far away. Latency still shows, through
   the round trip, as DEGRADED. Even at 2,000 bytes and more the rate includes
   latency, which is why `docs/ddil-results.md` calls it an estimate, not the
   link's capacity.
   </details>

6. You add a node-local event `node.<id>.passes.stale`. What fails until you
   finish, and what must you do?

   <details><summary>Answer</summary>

   `tests/docs/test_asyncapi.py` finds the new kind at its `subjects.local`
   call site and fails until `docs/icd/asyncapi.yaml` has a channel and a
   message for it, with a `Sentinel-Kind` header. Nothing needs changing at
   the leaf, because `node.>` is already denied both ways. The console streams
   it under its kind name.
   </details>

## Where next

- [Chapter 7, Priority sync](07-priority-sync.md): what the three cross-node subjects carry, and how the agent feeds and reads the link monitor.
- [Chapter 8, Operator data](08-operator-data.md): the `ops.<hub_id>.exchange` payload, and why signed entries survive a cleartext link.
- [Chapter 9, The DDIL harness](09-ddil-harness.md): the scenarios behind `docs/ddil-results.md`, on the cluster you started in Try it 4.
- [Chapter 10](10-passes-and-screening.md) for the unit behind the `unit.>` and `passes.>` denials, [chapter 11](11-ai-assistant.md) for the AI tier policy that reads the measured link, and [chapter 12](12-supply-chain-and-deploy.md) for installing `nats-server` from the templates.
- Reference: `docs/icd/asyncapi.yaml` (every subject, header and payload), `docs/technical-guide.md` ("The sync layer"), `docs/system-design.md` (ADR-004, ADR-009, ADR-010 and the NATS findings) and `SECURITY.md` (gap 2).
