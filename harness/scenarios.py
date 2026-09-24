"""Named DDIL scenarios. Each runs a real two-node cluster (cluster.py),
drives the link and the operators, and returns measured assertions.

    DENIED        cut the link; keep working on both sides; reconnect
    LIMITED       ~8 kbit/s: summaries first, then earliest deadline first,
                  measured against a FIFO baseline over the same link
    INTERMITTENT  repeated short drops while both sides write
    DEGRADED      high latency, 32 kB/s
    RECOVERY      DENIED straight to LIMITED: the leaf handshake over a thin link
    OPSEC         a unit set and its passes computed at the edge never reach the hub

Durations are wall-clock and stated in the results. The properties proven -
no loss, convergence, ordering, availability - do not depend on how long a
denial lasts, only on what is written during it; the nightly job runs a
longer denial to show that.
"""

from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
import time

from .cluster import ROOT, Cluster, http, wait_until

sys.path.insert(0, str(ROOT))

from sentinel.conjunction.exercise import generate  # noqa: E402

# Every scenario runs the hub's default configuration: it holds the public
# element-set snapshot and offers edges the imaging catalog the pass module
# uses (SENTINEL_SYNC_ELEMENTS=catalog), so those records share the link
# with the conjunction CDMs being measured.
DEFAULT_HUB = (
    "Default hub configuration: conjunction CDMs plus the imaging catalog's public element sets "
    "(SENTINEL_SYNC_ELEMENTS=catalog) share the link."
)
OPERATOR_EDGE = {"X-Sentinel-Operator": "maj.ortiz@edge-alpha"}
OPERATOR_HUB = {"X-Sentinel-Operator": "capt.lee@hub"}


class Result:
    def __init__(self, name: str):
        self.name = name
        self.assertions: list[dict] = []
        self.metrics: dict = {}
        self.notes: list[str] = []
        self.started = time.time()

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.assertions.append({"name": name, "passed": bool(passed), "detail": detail})
        return passed

    @property
    def passed(self) -> bool:
        return all(a["passed"] for a in self.assertions)

    def to_dict(self) -> dict:
        return {
            "scenario": self.name,
            "passed": self.passed,
            "assertions": self.assertions,
            "metrics": self.metrics,
            "notes": self.notes,
            "duration_s": round(time.time() - self.started, 1),
            "ran_at": dt.datetime.now(dt.UTC).isoformat(),
        }


# --------------------------------------------------------------------- helpers
def scenario_cdms(epoch: dt.datetime) -> tuple[list, list]:
    """(released by epoch, released later) KVN CDMs of the exercise scenario."""
    items = generate(epoch)
    return [i for i in items if i.release_at <= epoch], [i for i in items if i.release_at > epoch]


def post_cdm(base: str, kvn: str) -> dict:
    import urllib.request

    req = urllib.request.Request(f"{base}/api/ingest/cdm", data=kvn.encode(), method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        import json

        return json.loads(resp.read())


def active(base: str) -> list[dict]:
    return http("GET", f"{base}/api/events?scope=active")


def converged(c: Cluster) -> bool:
    hub = {e["event_id"]: e["cdm_count"] for e in active(c.hub)}
    edge_events = active(c.edge)
    edge = {e["event_id"]: e["cdm_count"] for e in edge_events}
    if hub != edge or not hub:
        return False
    if any(e.get("verification") != "VERIFIED" for e in edge_events):
        return False
    return http("GET", f"{c.hub}/api/ops/digest")["log"] == http("GET", f"{c.edge}/api/ops/digest")["log"] and (
        http("GET", f"{c.hub}/api/ops/digest")["annotations"] == http("GET", f"{c.edge}/api/ops/digest")["annotations"]
    )


def link_state(c: Cluster) -> str:
    return http("GET", f"{c.edge}/api/link")["monitor"]["state"]


def alive(c: Cluster) -> bool:
    return all(p.poll() is None for p in c.procs.values())


def kendall_tau(sequence: list[float]) -> float:
    """Rank agreement between arrival order and the values (1 = sorted)."""
    n = len(sequence)
    if n < 2:
        return 1.0
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            if sequence[i] < sequence[j]:
                concordant += 1
            elif sequence[i] > sequence[j]:
                discordant += 1
    total = concordant + discordant
    return 1.0 if total == 0 else (concordant - discordant) / total


# --------------------------------------------------------------------- DENIED
def denied(denial_s: float = 20.0) -> Result:
    r = Result("DENIED")
    r.notes.append(DEFAULT_HUB)
    r.metrics["denial_wall_s"] = denial_s
    epoch = dt.datetime.now(dt.UTC)
    initial, later = scenario_cdms(epoch)
    second_batch, _ = scenario_cdms(epoch + dt.timedelta(hours=3))
    with Cluster(hub_exercise=False, sync_interval_s=1.0) as c:
        for item in initial:
            post_cdm(c.hub, item.kvn)
        wait_until(lambda: converged(c), 60, what="initial convergence")
        dil = next(e for e in active(c.edge) if e["secondary"]["id"] == "99412")

        c.link("DENIED")
        t_cut = time.monotonic()
        # The edge keeps working: reads, decisions, triage - all local.
        latencies = []
        for _ in range(40):
            t0 = time.monotonic()
            events = http("GET", f"{c.edge}/api/events")
            latencies.append((time.monotonic() - t0) * 1000)
            assert events
        http("POST", f"{c.edge}/api/events/{dil['event_id']}/annotation",
             {"field": "triage_status", "value": "MANEUVER_PLANNING"}, OPERATOR_EDGE)
        http("POST", f"{c.edge}/api/events/{dil['event_id']}/decision",
             {"decision": "MANEUVER", "rationale": "Pc rising; worst case RED"}, OPERATOR_EDGE)
        # Meanwhile the hub keeps receiving: newer CDMs and new events.
        http("POST", f"{c.hub}/api/events/{dil['event_id']}/annotation",
             {"field": "triage_status", "value": "WATCH"}, OPERATOR_HUB)
        for item in later + second_batch:
            post_cdm(c.hub, item.kvn)
        hub_events = len(active(c.hub))

        denied_seen = wait_until(lambda: link_state(c) == "DENIED", 40, what="edge to measure DENIED")
        remaining = denial_s - (time.monotonic() - t_cut)
        if remaining > 0:
            time.sleep(remaining)
        edge_during = active(c.edge)
        r.metrics["edge_events_during_denial"] = len(edge_during)
        r.metrics["hub_events_during_denial"] = hub_events

        c.link("CONNECTED")
        t_reconnect = time.monotonic()
        arrivals_before = http("GET", f"{c.edge}/api/sync")["arrivals_total"]
        wait_until(lambda: converged(c), 120, what="reconnect convergence")
        r.metrics["convergence_after_reconnect_s"] = round(time.monotonic() - t_reconnect, 2)

        p95 = statistics.quantiles(latencies, n=20)[18]
        r.metrics["edge_api_p95_ms_while_denied"] = round(p95, 1)
        r.check("edge console stays available while denied (p95 < 200 ms)", p95 < 200, f"p95 {p95:.1f} ms over 40 requests")
        r.check("edge measured the link as DENIED (not configured - measured)", bool(denied_seen))

        hub_final = {e["event_id"]: e["cdm_count"] for e in active(c.hub)}
        edge_final = {e["event_id"]: e["cdm_count"] for e in active(c.edge)}
        r.check("no data loss: every hub CDM reached the edge (set difference empty)", hub_final == edge_final,
                f"{len(hub_final)} events, {sum(hub_final.values())} CDMs")
        r.check("every event re-assessed at the edge and VERIFIED against the hub",
                all(e["verification"] == "VERIFIED" for e in active(c.edge)))

        hd, ed = http("GET", f"{c.hub}/api/ops/digest"), http("GET", f"{c.edge}/api/ops/digest")
        r.check("operator data converged (log and annotations digests equal)",
                hd["log"] == ed["log"] and hd["annotations"] == ed["annotations"],
                f"{ed['entries']} log entries, {ed['registers']} annotation registers")

        ops = http("GET", f"{c.edge}/api/events/{dil['event_id']}/ops")
        values = {v["v"] for v in ops["annotations"]["triage_status"]["values"]}
        r.check("concurrent triage edits kept as a CONFLICT, not last-writer-wins",
                ops["annotations"]["triage_status"]["conflict"] and values == {"MANEUVER_PLANNING", "WATCH"},
                f"values {sorted(values)}")
        decision = next(e for e in ops["entries"] if e["kind"] == "DECISION")
        r.check("the decision made offline is flagged REVIEW REQUIRED (its CDM was superseded)",
                decision["review_required"], f"decided against {decision['event_ref'].get('message_id')}")
        r.check("the edge's offline decision is signed and verified at the hub",
                all(e["signature_valid"] for e in http("GET", f"{c.hub}/api/events/{dil['event_id']}/ops")["entries"]))

        arrivals = http("GET", f"{c.edge}/api/sync")["arrivals"][-(http('GET', f'{c.edge}/api/sync')['arrivals_total'] - arrivals_before):]
        latest = [a for a in arrivals if a["latest"]]
        classes = [a["class"] for a in arrivals]
        order_ok = classes == sorted(classes, key=lambda k: ["P0_SUMMARY", "P1_URGENT", "P2_ROUTINE", "P3_REFERENCE", "P4_BULK"].index(k))
        p1 = [dt.datetime.fromisoformat(a["deadline"]).timestamp() for a in latest if a["class"] == "P1_URGENT"]
        tau = kendall_tau(p1)
        r.metrics["catch_up_records"] = len(arrivals)
        r.metrics["catch_up_p1_kendall_tau"] = round(tau, 3)
        r.check("catch-up order: urgent before routine before history", order_ok, " > ".join(dict.fromkeys(classes)))
        r.check("catch-up order: earliest deadline first within urgent (Kendall tau >= 0.95)", tau >= 0.95, f"tau {tau:.3f} over {len(p1)} records")
        r.check("no process restarted", alive(c))
    return r


# -------------------------------------------------------------------- LIMITED
def _limited_run(mode: str) -> dict:
    epoch = dt.datetime.now(dt.UTC)
    initial, _ = scenario_cdms(epoch)
    with Cluster(sync_mode=mode, hub_exercise=False, sync_interval_s=0.5) as c:
        wait_until(c.leaf_connected, 20, what="leaf")
        c.link("LIMITED")
        time.sleep(2)
        for item in initial:
            post_cdm(c.hub, item.kvn)
        t0 = time.monotonic()
        hub_events = {e["event_id"]: e for e in active(c.hub)}
        urgent = min(
            (e for e in hub_events.values() if e["consequence"] in ("CRITICAL", "SERIOUS")),
            key=lambda e: e["mcp"],
        )
        times: dict = {}

        def poll() -> bool:
            events = {e["event_id"]: e for e in active(c.edge)}
            now = round(time.monotonic() - t0, 1)
            if "all_summaries" not in times and set(events) >= set(hub_events):
                times["all_summaries"] = now
            if "most_urgent_full" not in times and events.get(urgent["event_id"], {}).get("verification") == "VERIFIED":
                times["most_urgent_full"] = now
            if "all_latest_verified" not in times and set(events) >= set(hub_events) and all(
                e.get("verification") == "VERIFIED" for e in events.values()
            ):
                times["all_latest_verified"] = now
            return len(times) == 3

        wait_until(poll, 400, interval=0.5, what=f"{mode} LIMITED sync")
        sync = http("GET", f"{c.edge}/api/sync")
        return {
            "mode": mode,
            "times_s": times,
            "most_urgent_event": urgent["event_id"],
            "records": len(initial),
            "record_bytes": sum(len(i.kvn.encode()) for i in initial),
            "summary_only_marked": sync["summary_only"],
            "measured_rate_bytes_per_s": sync["link"]["rate_bytes_per_s"],
            "link_state": sync["link"]["state"],
        }


def limited() -> Result:
    r = Result("LIMITED")
    r.notes.append("Toxiproxy bandwidth 1 kB/s each way plus 600 ms latency; NATS leafnode s2_auto compression on.")
    r.notes.append(DEFAULT_HUB)
    edf = _limited_run("edf")
    fifo = _limited_run("fifo")
    r.metrics["edf"] = edf
    r.metrics["fifo"] = fifo
    speedup = fifo["times_s"]["most_urgent_full"] / max(edf["times_s"]["most_urgent_full"], 0.1)
    r.metrics["most_urgent_speedup"] = round(speedup, 1)
    r.check("every event visible as a summary before its full record (EDF)",
            edf["times_s"]["all_summaries"] <= edf["times_s"]["all_latest_verified"],
            f"summaries at {edf['times_s']['all_summaries']} s, all verified at {edf['times_s']['all_latest_verified']} s")
    r.check("most urgent full CDM arrives sooner with EDF than with FIFO (same link, same bytes)",
            edf["times_s"]["most_urgent_full"] < fifo["times_s"]["most_urgent_full"],
            f"EDF {edf['times_s']['most_urgent_full']} s vs FIFO {fifo['times_s']['most_urgent_full']} s ({speedup:.1f}x)")
    r.check("the edge measured the link as LIMITED", edf["link_state"] in ("LIMITED", "DEGRADED"),
            f"measured {edf['measured_rate_bytes_per_s']} B/s")
    return r


# ---------------------------------------------------------------- INTERMITTENT
def intermittent(flaps: int = 8, down_s: float = 3.0, up_s: float = 3.0) -> Result:
    r = Result("INTERMITTENT")
    r.notes.append(DEFAULT_HUB)
    r.metrics.update({"flaps": flaps, "down_s": down_s, "up_s": up_s})
    epoch = dt.datetime.now(dt.UTC)
    initial, later = scenario_cdms(epoch)
    extra, _ = scenario_cdms(epoch + dt.timedelta(hours=5))
    feed = later + extra
    with Cluster(hub_exercise=False, sync_interval_s=0.5) as c:
        for item in initial:
            post_cdm(c.hub, item.kvn)
        wait_until(lambda: converged(c), 60, what="initial convergence")
        event_id = active(c.hub)[0]["event_id"]
        written = 0
        for i in range(flaps):
            c.link("DENIED")
            for k in range(2):
                http("POST", f"{c.edge}/api/events/{event_id}/note", {"text": f"edge note {i}.{k}"}, OPERATOR_EDGE)
                written += 1
            http("POST", f"{c.hub}/api/events/{event_id}/note", {"text": f"hub note {i}"}, OPERATOR_HUB)
            written += 1
            if feed:
                post_cdm(c.hub, feed.pop(0).kvn)
            time.sleep(down_s)
            c.link("CONNECTED")
            time.sleep(up_s)
        for item in feed:
            post_cdm(c.hub, item.kvn)
        wait_until(lambda: converged(c), 120, what="final convergence")
        hd, ed = http("GET", f"{c.hub}/api/ops/digest"), http("GET", f"{c.edge}/api/ops/digest")
        r.metrics["notes_written"] = written
        r.check("no duplicate or lost log entries (count equals notes written, both nodes)",
                hd["entries"] == ed["entries"] == written, f"hub {hd['entries']}, edge {ed['entries']}, written {written}")
        r.check("operator data converged", hd["log"] == ed["log"])
        r.check("every hub CDM at the edge, VERIFIED", converged(c))
        r.check("no process restarted", alive(c))
    return r


# -------------------------------------------------------------------- DEGRADED
def degraded() -> Result:
    r = Result("DEGRADED")
    r.notes.append("Toxiproxy latency 600 +/- 200 ms each way, bandwidth 32 kB/s.")
    r.notes.append(DEFAULT_HUB)
    epoch = dt.datetime.now(dt.UTC)
    initial, _ = scenario_cdms(epoch)
    with Cluster(hub_exercise=False, sync_interval_s=1.0) as c:
        wait_until(c.leaf_connected, 20, what="leaf")
        c.link("DEGRADED")
        time.sleep(2)
        for item in initial:
            post_cdm(c.hub, item.kvn)
        t0 = time.monotonic()
        wait_until(lambda: converged(c), 180, what="convergence over a degraded link")
        r.metrics["convergence_s"] = round(time.monotonic() - t0, 1)
        state = link_state(c)
        r.metrics["measured_state"] = state
        r.metrics["link"] = http("GET", f"{c.edge}/api/link")["monitor"]
        r.check("converges over a degraded link", True, f"{r.metrics['convergence_s']} s")
        r.check("edge measured degradation (DEGRADED or LIMITED, not CONNECTED)", state in ("DEGRADED", "LIMITED"), state)
        r.check("no process restarted", alive(c))
    return r


# ------------------------------------------------------------------- RECOVERY
def recovery() -> Result:
    """Reconnecting over a thin link: DENIED straight to LIMITED.

    The leafnode handshake itself must complete over ~8 kbit/s. With default
    NATS settings it cannot (the hub's INFO outruns the 1 s first-INFO
    timeout) and the edge reconnects forever - found by the live demo.
    """
    r = Result("RECOVERY")
    r.notes.append(DEFAULT_HUB)
    epoch = dt.datetime.now(dt.UTC)
    initial, _ = scenario_cdms(epoch)
    with Cluster(hub_exercise=False, sync_interval_s=1.0) as c:
        for item in initial:
            post_cdm(c.hub, item.kvn)
        wait_until(lambda: converged(c), 60, what="initial convergence")
        c.link("DENIED")
        wait_until(lambda: link_state(c) == "DENIED", 40, what="DENIED measured")
        event_id = active(c.edge)[0]["event_id"]
        http("POST", f"{c.edge}/api/events/{event_id}/note", {"text": "written while denied"}, OPERATOR_EDGE)
        c.link("LIMITED")
        t0 = time.monotonic()
        wait_until(c.leaf_connected, 90, what="leaf reconnect over LIMITED")
        r.metrics["leaf_reconnect_s"] = round(time.monotonic() - t0, 1)
        wait_until(lambda: converged(c), 180, what="convergence over LIMITED")
        r.metrics["convergence_s"] = round(time.monotonic() - t0, 1)
        r.check("leaf re-establishes over ~8 kbit/s after a denial", True, f"{r.metrics['leaf_reconnect_s']} s")
        r.check("operator data written while denied reaches the hub over the thin link",
                http("GET", f"{c.hub}/api/ops/digest")["entries"] == 1, f"converged in {r.metrics['convergence_s']} s")
        r.check("no process restarted", alive(c))
    return r


# ---------------------------------------------------------------------- OPSEC
# The vendored snapshot's day, so element sets are fresh and the run is
# reproducible whatever day it runs on (a stale set's sync deadline has passed).
OPSEC_CLOCK = "sim:2026-09-24T06:00:00+00:00,1"
# An exercise position (ORIGINATOR=SENTINEL-EXERCISE), never a real unit.
OPSEC_UNIT = {"unit_id": "EX-OPSEC-UNIT-7", "lat_deg": 35.26417, "lon_deg": -116.68273, "alt_m": 701.0, "reaction_time_min": 30.0}
OPSEC_SETTLE_S = 8.0          # many sync cycles: time for anything that would leak to cross


def status_of(method: str, url: str, body: dict | None = None) -> int:
    import urllib.error

    try:
        http(method, url, body)
        return 200
    except urllib.error.HTTPError as exc:
        return exc.code


def _capture_summary(messages) -> str:
    return f"{len(messages)} messages, {sum(len(m.data) for m in messages):,} bytes"


def _subject_families(messages) -> str:
    """What the hub saw, by subject family: its own node events, sync and
    operator-data requests, replies to edge inboxes, the control canary."""
    families: dict[str, int] = {}
    for m in messages:
        tokens = m.subject.split(".")
        family = ".".join(tokens[:1] if tokens[0].startswith("_") else tokens[:3] if tokens[0] == "node" else tokens[:2])
        families[family] = families.get(family, 0) + 1
    return ", ".join(f"{family} {count}" for family, count in sorted(families.items(), key=lambda kv: -kv[1]))


def opsec() -> Result:
    """The unit's position never leaves the edge (ADR-010).

    Real hub and edge processes. The edge gets element sets from the hub by
    sync, is given a unit, and computes passes, while a subscriber to `>`
    on the hub's nats-server records everything the hub receives. Its
    interest reaches the edge over the leaf, so the edge forwards anything
    its leaf permissions allow: the adversarial case, not a sample.
    """
    from .opsec import Capture, find_leaks, leak_patterns, publish, scan_tree

    r = Result("OPSEC")
    r.notes.append(
        "NIST SP 800-53 AC-4 (information flow enforcement). The ground unit's position and the pass "
        "windows computed from it stay on the edge node: the application publishes only a coordinate-free "
        "node-scoped event, and the edge's leafnode permissions deny exporting unit.>, passes.> and node.>. "
        "Evidence: a subscriber to > on the hub's nats-server during a real edge computation, a deliberate "
        "canary publish of the unit at the edge, and a byte scan of every hub file."
    )
    patterns = leak_patterns(OPSEC_UNIT)
    nonce = f"opsec-control-{time.time_ns()}".encode()
    with Cluster(clock=OPSEC_CLOCK, hub_exercise=True, sync_interval_s=0.5) as c:
        hub_url, edge_url = (f"nats://127.0.0.1:{c.ports[p]}" for p in ("hub_client", "edge_client"))
        wait_until(c.leaf_connected, 20, what="leaf")
        with Capture(hub_url) as hub_wire, Capture(edge_url) as edge_wire:
            t0 = time.monotonic()
            wait_until(lambda: len(http("GET", f"{c.edge}/api/passes/catalog")["imagers"]) == 38, 120,
                       what="element sets at the edge through sync")
            r.metrics["element_sync_s"] = round(time.monotonic() - t0, 1)
            unit_put = status_of("PUT", f"{c.edge}/api/passes/unit", OPSEC_UNIT)
            answer = http("GET", f"{c.edge}/api/passes?hours=24")
            http("GET", f"{c.edge}/api/passes?hours=72")
            unit = json.dumps(OPSEC_UNIT).encode()
            publish(edge_url, [
                ("opsec.control", nonce),
                ("unit.edge-alpha.position", unit),
                ("passes.edge-alpha.windows", unit),
                ("node.edge-alpha.passes.updated", unit),
            ])
            time.sleep(OPSEC_SETTLE_S)
        hub_unit = status_of("GET", f"{c.hub}/api/passes/unit")
        hub_files = scan_tree(c.dir / "hub", patterns)
        hub_file_count = sum(1 for p in (c.dir / "hub").rglob("*") if p.is_file())
        hub_logs = {name: find_leaks((c.dir / name).read_bytes(), patterns) for name in ("hub.log", "nats-hub.log")}
        edge_files = scan_tree(c.dir / "edge-alpha", patterns)
        unit_file = c.dir / "edge-alpha" / "var" / "unit.json"
        unit_mode = oct(unit_file.stat().st_mode & 0o777) if unit_file.exists() else None
        edge_log_leaks = find_leaks((c.dir / "edge.log").read_bytes(), patterns)
        processes_alive = alive(c)

    hub_leaks = {m.subject: leaks for m in hub_wire.messages if (leaks := find_leaks(m.blob(), patterns))}
    pass_subjects = sorted({m.subject for m in hub_wire.messages if {"unit", "passes"} & set(m.subject.split("."))})
    element_sets_crossed = sum(m.headers.get("Sentinel-Event-Id", "").startswith("omm:") for m in hub_wire.messages)
    edge_updates = [m for m in edge_wire.messages if m.subject == "node.edge-alpha.passes.updated" and m.data != unit]
    control_crossed = any(m.subject == "opsec.control" and m.data == nonce for m in hub_wire.messages)

    r.metrics.update({
        "hub_messages_captured": len(hub_wire.messages),
        "hub_bytes_captured": sum(len(m.data) for m in hub_wire.messages),
        "hub_subjects": _subject_families(hub_wire.messages),
        "element_sets_crossed": element_sets_crossed,
        "leak_patterns_checked": len(patterns),
        "edge_windows_24h": len(answer["windows"]),
        "edge_gaps_24h": len(answer["gaps"]),
        "edge_passes_updated_events": len(edge_updates),
    })
    r.check("element sets reached the edge through sync (the edge loads none itself)",
            answer["catalog"]["imagers"] == 38 and element_sets_crossed >= 38,
            f"{element_sets_crossed} element sets crossed in {r.metrics['element_sync_s']} s; edge assessed {answer['catalog']['imagers']} imagers")
    r.check("the edge accepted the unit and computed its passes locally",
            unit_put == 200 and bool(answer["windows"]) and bool(answer["gaps"]),
            f"{len(answer['windows'])} windows, {len(answer['gaps'])} gaps over 24 h")
    r.check("control: the hub's capture sees what the edge exports (a harmless canary crossed)", control_crossed,
            f"hub capture: {_capture_summary(hub_wire.messages)}")
    r.check("control: the edge did publish passes.updated on its own bus", bool(edge_updates),
            f"{len(edge_updates)} events on node.edge-alpha.passes.updated")
    r.check("nothing on the hub's wire carries the unit id or its coordinates, in any serialization",
            not hub_leaks, f"{len(patterns)} patterns over {_capture_summary(hub_wire.messages)}" if not hub_leaks else str(hub_leaks))
    r.check("no pass or unit subject reached the hub, not even a deliberate canary on unit.>, passes.> or node.>",
            not pass_subjects, "none" if not pass_subjects else ", ".join(pass_subjects))
    r.check("the hub has no unit (GET /api/passes/unit is 404)", hub_unit == 404, f"HTTP {hub_unit}")
    r.check("no file on the hub holds the unit (var, database, NATS config, logs)",
            not hub_files and not any(hub_logs.values()),
            f"{hub_file_count + len(hub_logs)} files scanned" if not hub_files else str(hub_files))
    r.check("control: on the edge the unit rests only in var/unit.json, mode 0600",
            list(edge_files) == ["var/unit.json"] and unit_mode == "0o600" and not edge_log_leaks,
            f"files holding the unit: {sorted(edge_files)}; mode {unit_mode}")
    r.check("no process restarted", processes_alive)
    return r


SCENARIOS = {
    "denied": denied,
    "limited": limited,
    "intermittent": intermittent,
    "degraded": degraded,
    "recovery": recovery,
    "opsec": opsec,
}
