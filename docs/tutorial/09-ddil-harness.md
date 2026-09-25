# 9. The DDIL harness

## What you will learn

- Why Sentinel's link claims are measured on real processes over a shaped TCP link, not on mocks.
- What each of the six scenarios does to the link and what it asserts.
- How the LIMITED comparison between earliest-deadline-first and FIFO was made fair, and why it reports medians.
- Where the harness gets its counts, and why a NATS capture can prove only that nothing leaked.
- How to run one scenario, read its result, and know when the committed report may be regenerated.

## Why it exists

Chapters 6 to 8 make promises about a bad link: the edge console keeps working when the link is cut, nothing is lost, and the urgent record crosses first. Chapter 10 adds one more: a unit's position never leaves the edge. Unit tests check the logic behind each promise with an in-process bus. They cannot check the promise itself, because the promise is about real TCP, a real NATS leafnode connection and real timeouts.

The harness is where those promises are measured. It starts a hub and an edge as real processes on one machine, puts an emulated link between them, and runs named scenarios that assert what an operator would see. The results go into `docs/ddil-results.md`, the only place Sentinel's link numbers come from. Every ADR that quotes a link number points there.

It has already paid for itself. Running on real processes, in the harness and in the live demo built on it, found four NATS defaults that assume a LAN. One of them meant the edge could never reconnect over a thin link. Section "Findings from the DDIL harness" in `docs/system-design.md` lists them, and each now has a scenario guarding it.

## Concepts

### The topology

```
edge node                                                               hub node
sentinel serve --> nats-server --leaf--> Toxiproxy --> nats-server <-- sentinel serve
(role edge)        (edge's own bus)      (the link)    (hub's own bus)   (role hub)
```

Each node talks only to its own `nats-server`. The two nodes share nothing but the NATS leafnode link, and Toxiproxy sits on that one TCP connection. The harness shapes the link by talking to Toxiproxy directly. The nodes are never told what the link is doing: the edge measures it (`LinkMonitor`, chapter 6). So the check "edge measured the link as DENIED" means something.

### Why real processes

A mock of the link encodes your beliefs about the link. The bugs that matter are the ones where those beliefs are wrong. On real processes:

- the leaf handshake has to fit through about 8 kbit/s with 600 ms of latency, and with the default timeouts it did not;
- a denied link is a black hole, not a polite reset, and NATS detects it only by missing pings;
- NATS picks the leaf's compression from a round trip it measured, which decides how long a CDM takes;
- the hub's listener advertised its own address, and the edge reconnected around the emulated link.

None of these shows up in-process. The binaries are pinned with a locally computed sha256 in `deploy/tools.lock` and fetched by `make tools` into `.tools/<arch>/`. They are static, so the same harness runs in WSL, on a laptop and in CI, with no containers. (The Compose stack in `deploy/compose/` runs the same topology in containers, from the same config rendering; chapter 12 covers it.)

The in-process tests stay, for speed. `tests/sync/` runs the same agent over `InProcessBus`, and `ThinLinkBus` in `tests/sync/test_hostile_hub.py` loses any reply that could not cross a thin link within the requester's timeout. The harness is the slow, honest check above them.

### The link presets

`PRESETS` in `sentinel/linkstate/toxiproxy.py` defines four link states as Toxiproxy "toxics" on each direction of the leaf connection:

| Preset | What Toxiproxy does |
|---|---|
| CONNECTED | nothing |
| DEGRADED | 600 ± 200 ms latency, 32 KB/s |
| LIMITED | 600 ± 100 ms latency, 1 KB/s (about 8 kbit/s) |
| DENIED | data on the live connection vanishes (timeout toxic), and the proxy refuses new connections |

Toxiproxy shapes a TCP stream. It adds delay, limits bandwidth and black-holes data, but it does not drop packets. TCP would retransmit them anyway, so loss shows up as delay.

### The six scenarios

All six are in `harness/scenarios.py`. Each runs the hub's default configuration: conjunction CDMs, plus the imaging catalog's public element sets, share the link.

| Scenario | What it does to the link | What it asserts |
|---|---|---|
| DENIED | cuts the link while both sides write and the hub receives newer CDMs, then reconnects | the edge console answers (p95 under 200 ms); the edge measured DENIED; every hub CDM reaches the edge and is VERIFIED; operator data converges; the concurrent triage edits show as a CONFLICT; the offline decision is flagged REVIEW_REQUIRED and its signature verifies at the hub; catch-up order is urgent, then routine, then history, with earliest deadline first inside urgent |
| LIMITED | about 8 kbit/s; the same backlog pulled in EDF order and in FIFO order, repeatedly | same link, same backlog and same records in every run; every summary visible before the most urgent full record; that record arrives sooner with EDF (medians); the edge measured LIMITED |
| INTERMITTENT | eight drops of 3 s, with 3 s up between them, while both sides write notes | the log holds exactly the notes written, on both nodes; operator data converges; every CDM is VERIFIED |
| DEGRADED | high latency and 32 KB/s | convergence within 180 s; the edge measured DEGRADED or LIMITED, not CONNECTED |
| RECOVERY | DENIED straight to LIMITED | the leaf re-establishes over the thin link; a note written while denied reaches the hub |
| OPSEC | CONNECTED; a unit is set at the edge, its passes computed, and the unit is deliberately published on forbidden subjects | nothing on the hub's wire or disk holds the unit in any of 23 forms; no `unit.>`, `passes.>` or `node.>` subject reached the hub; the hub has no unit; controls prove the capture could see what the edge exports |

Every scenario also checks "no process restarted". A property that only holds because a process crashed and came back is not a property.

### The simulated clock

Every node asks one `Clock` what time it is (`sentinel/clock.py`), chosen by `SENTINEL_CLOCK`: `real`, `fixed:<instant>` for tests, or `sim:<epoch>,<scale>`, which starts at the epoch and runs `scale` times wall speed. The harness uses the simulated clock for reproducibility, not speed. LIMITED and OPSEC run both nodes from `SNAPSHOT_CLOCK`, the vendored element-set snapshot's day at scale 1. The element sets are then fresh, and their order against the exercise CDMs, which are generated from the same epoch, is the same whatever day the scenario runs. DENIED, INTERMITTENT, DEGRADED and RECOVERY use the real clock and generate their CDMs from "now".

Durations are wall-clock and reported as such. The properties the scenarios prove (no loss, convergence, order, availability) depend on what is written during a denial, not on how long it lasts. The nightly CI job repeats DENIED with a 900 s denial to show that.

### Counting from the node's own record

A harness needs counts: which records the edge fetched, in what order, and how many. There are two places to get them.

- **A capture.** Subscribe to everything on a `nats-server` and record it. A capture only sees what crosses after it has subscribed and its interest has reached the other server. The edge may already have fetched records by then. So a capture can undercount arrivals, and a count from it is a race.
- **The edge's own record.** `GET /api/sync` on the edge returns a running total, `arrivals_total`, and the 50 most recent arrivals. `SyncLedger` in `harness/ledger.py` reads it repeatedly and appends only arrivals it has not seen. When more than 50 arrived between two reads, it counts the ones it never saw in `unseen` instead of guessing. The checks that need every arrival (DENIED's order check, LIMITED's workload check) fail if `unseen` is not zero.

So the rule, stated in `CLAUDE.md`: counts come from a node's own record. A NATS capture is used for one thing, which is evidence of absence. If it saw nothing with the unit in it, and a control shows it could see what the edge exports, nothing leaked while it listened. It can never say what arrived.

### A fair comparison

LIMITED compares two orders for the same work: Sentinel's earliest-deadline-first (EDF) and hub arrival order (FIFO, `SENTINEL_SYNC_MODE=fifo`, the order a stream mirror would deliver). An early single run said FIFO verified every event sooner, with a link-rate reading many times higher. The modes had not run on equal links (ADR-006, "How the comparison is kept fair"). The scenario now holds every run to the same conditions and checks them:

1. **The same shaped link, from the first byte.** `Cluster(initial_link="DENIED")` disables the proxy before either `nats-server` starts. The backlog is posted to the hub while the link is down. Then the harness applies LIMITED and waits for the leaf to connect over it. The clock starts at link-up.
2. **The same backlog, and nothing crossing early.** `records_before_link_up` must be 0 in every run.
3. **Compression pinned.** NATS `s2_auto` picks each side's compression from a round trip it measured. A leaf that connects before shaping can keep `s2_uncompressed` for a whole run, and every CDM then takes far longer. Connecting over the shaped link makes both sides measure it and pick `s2_best`. The harness reads each side's compression from `/leafz` at link-up and at the end, with the toxics from Toxiproxy, and `link_mismatches` names any run that differed.
4. **The same records.** Each run's records fetched, bytes and `SyncLedger.digest()` (a hash of the set of records) must be identical across all runs of both modes.
5. **Repeated runs, medians and ranges.** Each mode runs N times (5 in `make ddil`, 3 in CI), each on a fresh cluster, alternating which mode goes first (`run_order`). `summarize` reports the median and the range of every time. The speed-up is the ratio of the two medians, never of one lucky pair.

A median of five ignores one bad run, where a mean would be dragged by it. The range is printed next to it, so a noisy measurement looks noisy.

### All six or none

`docs/ddil-results.md` is generated, and it is committed. Suppose someone runs one scenario on a fresh clone and then regenerates the report. Five scenarios would vanish from the committed evidence, silently. So `harness.report` writes the report from all six results or not at all. With any missing it names them and exits 1, or 0 with `--if-complete`, which is what `make opsec` passes. `make ddil` is the way to regenerate it: it runs all six, then writes the report.

### The machine-load column

Some results are latencies and times, and they move when the machine is busy. Each result records the 1-minute load average at its start and end (`load_1min` in `harness/scenarios.py`), and so does each LIMITED run. The report prints both. A slow number next to a high load reads differently from a slow number on an idle machine. The load average lags by design, so it says how busy the machine was around the run, not at each moment. It is recorded, not controlled: the harness does not refuse to run on a busy machine.

## Code walkthrough

### `harness/run.py`

The command line. `parse` takes scenario names (or `all`), `--denial-s` for DENIED and `--limited-runs` for LIMITED. `options_for` hands each scenario only its own options. `main` runs each scenario, prints its checks, writes `harness/results/<scenario>.json` (git-ignored) and exits 1 if any check failed.

Easy to get wrong: a scenario that raises is not lost. `main` catches it, records a failed "scenario ran to completion" check with the exception, prints the traceback, and still writes the JSON. Several checks are recorded as `True` because reaching that line proves them. DEGRADED's "converges over a degraded link" is one: when it fails, it fails as a `wait_until` timeout, which becomes the "ran to completion" failure.

### `harness/cluster.py`

`Cluster` is the two-node deployment.

- `allocate_ports` binds every port before releasing any, so no two processes get the same port. Nothing binds 8000 or 8001 unless a caller passes them, which only `harness/demo.py` does.
- `hub_nats_conf` and `edge_nats_conf` render `deploy/nats/hub.conf.tmpl` and `deploy/nats/edge.conf.tmpl`. The Compose stack uses the same functions.
- `_identities` enrols both nodes into one trust file through `harness/identity.py` (chapter 8).
- `start` checks the binaries, starts Toxiproxy, creates the `leaf` proxy, applies `initial_link`, then starts both `nats-server` processes and both nodes with `sentinel serve`. The edge gets `SENTINEL_SYNC_MODE`, the sync interval and the demo controls.
- `link`, `toxics`, `leafz`, `leaf_connected`, `leaf_compression` and `link_now` control the link and read it back.
- `stop` terminates, waits, then kills, and removes the temporary directory unless `keep=True`. `logs(name)` tails a process log.

Easy to get wrong: `initial_link`. The default is CONNECTED, which is right for scenarios that start converged. A scenario that measures from the first byte must start DENIED, or records cross before the clock starts.

### `harness/scenarios.py`

`Result` collects checks, metrics, notes and the load at start and end. The helpers read the nodes over HTTP:

- `converged` means the same events with the same CDM counts on both sides, every edge event VERIFIED, and equal log and annotation digests;
- `link_state` is what the edge measured;
- `alive` says whether every process is still running;
- `kendall_tau` measures how well arrival order matches deadline order, where 1 means sorted.

Then one function per scenario, and `SCENARIOS` maps names to them.

The LIMITED code splits into three parts:

- `_limited_run` is one run from the fixed start;
- `limited_milestones` decides, from one look at the edge, which of the four timed moments it has reached: every summary visible, the most urgent full record VERIFIED, every event VERIFIED, and the queue settled;
- `limited` repeats runs and checks the fairness conditions.

`tests/test_harness_limited.py` holds the milestones to their meaning.

Easy to get wrong: the milestone "all records" is "settled", not "delivered". Admission control may hold a record SUMMARY-ONLY because it cannot arrive before its deadline. Such a run would move fewer records than the others, and the "same records" check would say so.

### `harness/ledger.py`

`SyncLedger.record` does the arithmetic above: new arrivals are the running total, minus `after`, minus what it already holds and has counted unseen. `after` lets DENIED count only the catch-up after reconnect. `items(prefix)` gives distinct item ids, which OPSEC uses to count element sets. `digest()` hashes the set of records fetched, in any order. `tests/test_harness_ledger.py` covers overlapping reads, arrivals before the first read, scroll-out and duplicates.

### `harness/stats.py`

`spread` returns the median, minimum, maximum and count, and refuses an empty list rather than returning zero. `describe` prints "median (min–max)". `summarize` spreads every time and counter over one mode's runs. `speedup` is the ratio of medians. `run_order` alternates the mode that goes first. `link_mismatches` compares each run's toxics and compression, at start and end, with the expected link. Toxic order does not matter, but every field does (`tests/test_harness_stats.py`).

### `harness/opsec.py`

`leak_patterns` lists every form the unit could travel or rest in: its id, each coordinate as text at 4, 5 and 6 decimals and as written, as 32- and 64-bit floats in both byte orders (the form CBOR uses), and its Earth-fixed position in km and m. That makes 23 patterns. `find_leaks` and `scan_tree` search bytes and files. `Capture` subscribes to `>` on one server from a background thread. `publish` sends the canaries from a fresh client.

Easy to get wrong: subscribing to `>` on the hub is the adversarial case, not a sample. The subscription's interest travels to the edge over the leaf, so the edge forwards everything its leaf permissions allow. That is why a clean capture, with the control canary crossing, means the permissions hold.

### `harness/report.py`

`missing` lists scenarios with no result. `main` refuses a partial set. `render` writes the summary table (result, checks passed, load at start and end, when each scenario ran), each scenario's notes and checks, and a metrics table. `limited_section` writes the medians and ranges per mode, the workload both modes moved, a paragraph saying the edge's rate estimate is not the link's capacity, and every run in the order run with its load. `tests/test_harness_report.py` holds all of it.

### `harness/demo.py`

The live demo: the same `Cluster`, with the web console, on 8000 and 8001. Its docstring has the four-step sequence (CONNECTED, DENIED, LIMITED, CONNECTED), and `docs/demo-script.md` has the full walk-through. Before starting, it loads the gitignored `.env` (`sentinel/localenv.py`), so hosted-AI keys reach both nodes; the scenarios do not. It measures nothing.

## Try it

Nothing below binds ports 8000 or 8001, so a live demo started with `make demo-local` keeps running: `Cluster` picks free ports. Do not run `make ddil` while working through this chapter. It takes a long time, and it rewrites the committed report.

**Fetch the pinned binaries.**

```bash
make tools
```

It prints one line per tool with its version, architecture and path under `.tools/`. A hash mismatch aborts before anything is written.

**Run a short scenario.**

```bash
uv run python -m harness.run recovery
uv run python -m harness.run denied
```

Each takes under a minute; DENIED holds the link down for its default 20 s. Each prints `=== NAME`, one `[PASS]` or `[FAIL]` line per check with its detail, and a `metrics:` line. In DENIED, look for these:

- the edge measured DENIED;
- the triage values listed as a CONFLICT;
- "decided against" naming the CDM the offline decision was made on, which a later CDM superseded;
- the catch-up classes in order.

Times and latencies differ from `docs/ddil-results.md` and from run to run. That is why the report states load and ranges.

**Read a result.**

```bash
uv run python -m json.tool harness/results/denied.json | head -40
```

The keys are `scenario`, `passed`, `assertions`, `metrics`, `notes`, `duration_s`, `ran_at` and `load_1min`. `harness/results/` is git-ignored: results are raw material, and only the report is committed.

**Run LIMITED once per mode.**

```bash
uv run python -m harness.run limited --limited-runs 1
```

This takes several minutes: each run is a fresh cluster and a full backlog over about 8 kbit/s. Check these in the output:

- all six checks pass;
- "records before link-up: [0]";
- the same record count and bytes "in each of 2 runs";
- "s2_best compression on both sides";
- the EDF and FIFO times for the most urgent record, "medians over 1 runs per mode".

With one run per mode, the median is that run, and no range is printed. With `--limited-runs 3` or more, the ranges appear.

**Poke at the pieces.** Start `uv run python` at the repository root:

```python
>>> from harness.ledger import SyncLedger
>>> arrival = lambda n: {"event_id": f"EV{n}", "sha": f"{n:016x}"}
>>> ledger = SyncLedger()
>>> ledger.record({"arrivals_total": 3, "arrivals": [arrival(n) for n in range(3)]})
>>> ledger.record({"arrivals_total": 60, "arrivals": [arrival(n) for n in range(10, 60)]})
>>> len(ledger.arrivals), ledger.unseen
(53, 7)
>>> from harness.stats import spread, describe, run_order
>>> run_order(3)
['edf', 'fifo', 'fifo', 'edf', 'edf', 'fifo']
>>> describe(spread([9.1, 8.6, 9.4, 9.1, 30.2]))
'9.1 s (8.6–30.2)'
>>> from harness.opsec import leak_patterns
>>> from harness.scenarios import OPSEC_UNIT
>>> len(leak_patterns(OPSEC_UNIT))
23
>>> from harness.report import missing
>>> missing()
```

The ledger saw 57 new arrivals but only 50 in the window, so it holds 53 and says 7 went unseen. The one slow run moves the range, not the median. `missing()` lists the scenarios you have not run. While it lists anything, `uv run python -m harness.report` refuses: it prints the missing names, writes nothing and exits 1. When `missing()` returns an empty list, do not run it here: it would rewrite `docs/ddil-results.md`.

**The offline tests.**

```bash
uv run pytest -q tests/test_harness_*.py
```

These take about a second and start no processes. They cover the ledger, the statistics, the milestones, the report's all-or-none rule, the OPSEC detector, port allocation and enrolment.

**Keep a cluster's logs.** In a REPL, `c = Cluster(keep=True).start()` and later `c.stop()` leave `c.dir` behind, holding `hub.log`, `edge.log`, `nats-hub.log`, `nats-edge.log`, `toxiproxy.log`, the rendered NATS configs, both databases and the trust file.

## Design choices

- **Real processes, not mocks** ([ADR-004](../system-design.md#adr-004--modular-monolith-with-an-internal-event-bus); [the findings](../system-design.md#findings-from-the-ddil-harness-nats-defaults-assume-a-lan)). Buys: the same code and configuration an edge runs, and the four NATS defaults found and guarded. Costs: minutes per run, pinned binaries to fetch, and times that move with the machine. Rejected: a simulated link in-process, which stays as the fast unit layer and cannot find a wrong timeout. Containers were not rejected; they are a second way to run the same topology, not the harness's default.
- **Toxiproxy on the leaf's TCP connection.** Buys: no privileges, one connection shaped and not the whole host, and control over HTTP from Python. Costs: no packet loss, and bandwidth set in whole KB/s.
- **Counts from the node's own record** (`CLAUDE.md`). Buys: counts without a race. Costs: the harness depends on the edge's status endpoint and its 50-arrival window, so `unseen` has to be counted and checked.
- **A baseline in the same agent** ([ADR-008](../system-design.md#adr-008--reference-data-application-level-priority-pull-not-transport-replication)). Buys: FIFO and EDF move the same bytes over the same transport, so only the order differs. Costs: the baseline is Sentinel's own FIFO mode, not a JetStream mirror. ADR-008 argues a mirror delivers in exactly that order.
- **Medians of repeated runs, alternating order, with every run listed** ([ADR-006](../system-design.md#adr-006--bandwidth-triage-by-decision-urgency)). Buys: one bad run cannot make or break the headline, and the reader sees every run. Costs: LIMITED dominates the time `make ddil` takes.
- **The simulated clock at scale 1.** Buys: reproducible element-set ages and orders, whatever the date. Costs: a six-hour denial is not run. The claim rests on the argument that length does not matter, backed by the nightly 900 s denial.
- **All six or none.** Buys: the committed report is always one complete set. Costs: regenerating it means running everything.
- **Load recorded, not controlled.** Buys: honest context for every time. Costs: nothing stops a run on a busy machine; the reader has to look.

## How it fails

- **Missing binaries.** `Cluster.start` exits with the path it looked for and "run `make tools`".
- **A scenario that raises**, including a `wait_until` timeout. `wait_until` names what it waited for and the last error. `harness.run` records the failed "scenario ran to completion" check, prints the traceback, writes the JSON and exits 1.
- **A process that dies.** The "no process restarted" check fails. `Cluster.logs` and `keep=True` show why. The demo prints the dead process's log and exits.
- **An unfair LIMITED run.** A different link, compression, backlog or workload is a failed check naming the run and the point, never a quiet median.
- **Arrivals the harness could not read.** Counted in `unseen`, and the checks that need every arrival fail.
- **A partial result set.** `harness.report` names what is missing and writes nothing. It checks that all six results exist, not that they come from one run or one commit. The summary table's "ran" column shows when each scenario ran, so a stale result is visible. `make ddil` avoids the problem by running all six first.
- **A busy machine.** Nothing refuses. The load column shows it, and in LIMITED so does each run's row.
- **A failed check in the report.** The report prints it as **FAIL**, in bold, in the summary table and in the scenario's list. `harness.report` renders whatever the results say.

## Check yourself

1. Why does each LIMITED run start with the link DENIED before either `nats-server` starts, rather than applying LIMITED to a running cluster?

   <details><summary>Answer</summary>So nothing crosses an unshaped link. No record slips across before the clock starts, the edge's rate estimate begins on the thin link, and NATS `s2_auto` picks its compression from a round trip measured on the thin link. A leaf that connected first could keep no compression for a whole run, and the two modes would not share a link.</details>

2. OPSEC counts the element sets that reached the edge from `GET /api/sync` on the edge, not from the capture on the hub. Why?

   <details><summary>Answer</summary>The capture sees only what crosses after it subscribes and its interest reaches the edge. Early fetches can happen before that, so a capture undercounts, and a check built on it fails by race. The edge's own record counts every arrival since it started. The capture is kept for what it can prove: that nothing carrying the unit crossed while it listened.</details>

3. OPSEC publishes a harmless canary on `opsec.control` at the edge and requires it to reach the hub's capture. What would a passing "nothing leaked" check mean without it?

   <details><summary>Answer</summary>Nothing. A capture that is not connected, not subscribed or not receiving would also see no leak. The canary shows the capture sees what the edge exports, so its silence about the unit is evidence.</details>

4. On a fresh clone you run `uv run python -m harness.run opsec`, then `make opsec`. What happens to `docs/ddil-results.md`?

   <details><summary>Answer</summary>Nothing. `make opsec` runs `harness.report --if-complete`. Five scenarios have no result, so it names them, writes nothing and exits 0. Without `--if-complete` it would exit 1. Either way one scenario cannot replace the committed six.</details>

5. DEGRADED records "converges over a degraded link" as `True` unconditionally. How can that check ever fail?

   <details><summary>Answer</summary>The line runs only after `wait_until(converged, 180)` returns. If convergence takes longer, `wait_until` raises `TimeoutError`, the scenario stops, and `harness.run` records a failed "scenario ran to completion" check with the error. So the failure shows, just under a different name.</details>

6. Four LIMITED EDF runs deliver the urgent record in about 9 s, and one takes 30 s, with that run's load several times higher. What does the report say, and what should you conclude?

   <details><summary>Answer</summary>The median stays about 9 s and the range shows the 30 s. The per-run table shows that run and its load. Conclude that the machine was busy for that run, not that the link or the order changed. That is why the harness reports medians and ranges and lists every run, not a mean.</details>

7. Why does `SyncLedger` count arrivals it never saw instead of estimating them, and which checks depend on that?

   <details><summary>Answer</summary>An unseen arrival might be the one out of order, or might differ between runs. Guessing would hide exactly what the check is for. DENIED's catch-up order check and LIMITED's "same records, every arrival read" check both require `unseen` to be zero.</details>

8. LIMITED and OPSEC run node clocks from the element-set snapshot's day, while DENIED uses the real clock. Why the difference?

   <details><summary>Answer</summary>LIMITED and OPSEC depend on the element sets. Their freshness, and FIFO's order of element sets against CDMs, depend on "now" relative to the snapshot. Running from the snapshot's epoch makes those runs the same whatever day they run. DENIED's checks are about the CDMs it generates from "now", so the real clock is fine.</details>

## Where next

- [10. Passes and screening](10-passes-and-screening.md) explains what the OPSEC scenario protects and the leaf permissions that do it (ADR-010).
- [12. Supply chain and deployment](12-supply-chain-and-deploy.md) covers `deploy/tools.lock`, `make tools` and the Compose stack that runs this topology in containers.
- [13. Keeping it honest](13-guardrails-compliance-mbse.md) shows how the numbers quoted from `docs/ddil-results.md` are held to it by `tests/doc_claims.toml`.
- [14. End to end](14-end-to-end.md) follows one CDM through a live hub and edge.
- Reference: [`docs/ddil-results.md`](../ddil-results.md) for every measured number; ADR-006's "How the comparison is kept fair" in [`docs/system-design.md`](../system-design.md); "The DDIL harness" in [`docs/technical-guide.md`](../technical-guide.md); and `.github/workflows/harness.yml` for how CI runs each scenario.
