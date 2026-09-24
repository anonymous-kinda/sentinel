"""Edge side: pull what matters most, first, over whatever link exists.

One cycle:

  1. Operator data (P0). One request carries this node's CRDT contexts and
     everything the hub was last known to lack; the reply carries
     everything this node lacks. State-based: a lost reply just means the
     next cycle sends a little more.
  2. Manifest (P0). Compact summaries of every active event, so the
     console shows the whole picture - marked HUB-ASSERTED - within
     seconds, even on a thin link. Skipped when unchanged (digest).
  3. Full CDMs. The want-list is a set difference - the hub's CDMs minus
     this node's - ordered by the mission-agnostic triage key: class, then
     earliest deadline (the maneuver commit point), then consequence.
     Admission control: if the measured link cannot deliver a record before
     its deadline, the event is marked SUMMARY-ONLY instead of spending the
     link on it. Each CDM is re-assessed here, and the result is compared
     with what the hub asserted (VERIFIED / MISMATCH).

Mode "fifo" replaces step 3's order with hub arrival order and turns
admission control off: the same transport and the same bytes, used as the
measured baseline in the LIMITED scenario.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import json
import time

from ..bus import Bus, NoResponders, RequestTimeout, subjects
from ..clock import Clock
from ..crdt import codec
from ..linkstate import LinkMonitor
from ..obs import get_logger
from ..triage import Consequence, PriorityClass, TriageKey, order
from .records import ReferenceRecords

log = get_logger(__name__)

LINK_ERRORS = (RequestTimeout, NoResponders, ConnectionError, OSError)


@dataclasses.dataclass
class WantItem:
    event_id: str
    sha16: str
    size: int
    created: int
    latest: bool
    key: TriageKey
    status: str = "QUEUED"          # QUEUED | FETCHING | ARRIVED | SUMMARY_ONLY
    eta_s: float | None = None

    def view(self, now: dt.datetime) -> dict:
        return {
            "event_id": self.event_id,
            "sha": self.sha16,
            "bytes": self.size,
            "class": self.key.klass.name,
            "deadline": None if self.key.deadline is None else self.key.deadline.isoformat(),
            "seconds_to_deadline": None if self.key.deadline is None else (self.key.deadline - now).total_seconds(),
            "latest": self.latest,
            "status": self.status,
            "eta_s": self.eta_s,
        }


class SyncAgent:
    def __init__(
        self,
        bus: Bus,
        records: ReferenceRecords,
        ops,
        clock: Clock,
        node_id: str,
        hub_id: str,
        link: LinkMonitor,
        mode: str = "edf",
        interval_s: float = 2.0,
        urgent_window_s: float = 72 * 3600.0,
    ):
        if mode not in ("edf", "fifo"):
            raise ValueError("mode must be edf or fifo")
        self.bus = bus
        self.records = records
        self.ops = ops
        self.clock = clock
        self.node_id = node_id
        self.hub_id = hub_id
        self.link = link
        self.mode = mode
        self.interval_s = interval_s
        self.urgent_window_s = urgent_window_s
        self.queue: list[WantItem] = []
        self.arrivals: list[dict] = []
        self.summary_only: set[str] = set()
        self.manifest_digest: str | None = None
        self.last_cycle: dict = {}
        self.started_wall = time.monotonic()
        self._last_state = None

    # ------------------------------------------------------------------ helpers
    def _timeout(self, expected_bytes: int) -> float:
        rate = self.link.rate_bytes_per_s or 1000.0
        return 6.0 + 1.5 * expected_bytes / max(rate, 400.0)

    async def _publish(self, kind: str, payload: dict) -> None:
        await self.bus.publish(
            subjects.local(self.node_id, kind),
            json.dumps(payload, default=str).encode(),
            {"Sentinel-Kind": kind},
        )

    async def _link_changed(self) -> None:
        state = self.link.state
        if state != self._last_state:
            self._last_state = state
            await self._publish("link.state", self.link.snapshot())

    # ------------------------------------------------------------------- cycle
    async def run(self) -> None:
        while True:
            try:
                await self.cycle()
            except LINK_ERRORS as exc:
                self.link.observe_failure()
                self.last_cycle = {"error": type(exc).__name__, "at": self.clock.now().isoformat()}
            except Exception:  # noqa: BLE001 - the agent must outlive any single bug
                log.exception("Sync cycle failed", hub_id=self.hub_id, mode=self.mode)
                self.link.observe_failure()
            await self._link_changed()
            await self._publish("sync.progress", self.status())
            await asyncio.sleep(self.interval_s)

    async def cycle(self) -> None:
        started = time.monotonic()
        ops_stats = await self.exchange_ops()
        manifest = await self.fetch_manifest()
        if manifest is not None:
            self.apply_manifest(manifest)
        fetched = await self.pull()
        self.last_cycle = {
            "at": self.clock.now().isoformat(),
            "duration_s": round(time.monotonic() - started, 2),
            "ops": ops_stats,
            "manifest_changed": manifest is not None,
            "fetched": fetched,
        }

    # ------------------------------------------------------------ operator data
    async def exchange_ops(self) -> dict:
        peer = self.ops.peer_contexts(self.hub_id)
        push = self.ops.payload_for(peer["log_ctx"], peer["mv_ctx"])
        request = codec.encode({"from": self.node_id, **self.ops.contexts(), "push": push})
        t0 = time.monotonic()
        reply_msg = await self.bus.request(
            subjects.ops_exchange(self.hub_id), request, timeout=self._timeout(len(request) + 2000)
        )
        rtt = time.monotonic() - t0
        reply = codec.decode(reply_msg.data)
        merged = await self.ops.merge_payload(reply["pull"])
        self.ops.remember_peer(self.hub_id, reply["ctx"])
        self.link.observe_success(rtt, len(request) + len(reply_msg.data), rtt)
        return {
            "sent_entries": len(push["log"]),
            "sent_registers": len(push["reg"]),
            **merged,
            "bytes": len(request) + len(reply_msg.data),
        }

    # ---------------------------------------------------------------- manifest
    async def fetch_manifest(self) -> list[dict] | None:
        request = codec.encode({"from": self.node_id, "known": self.manifest_digest})
        t0 = time.monotonic()
        reply = await self.bus.request(subjects.sync_manifest(self.hub_id), request, timeout=self._timeout(4000))
        rtt = time.monotonic() - t0
        self.link.observe_success(rtt, len(reply.data), rtt)
        if reply.headers.get("Sentinel-Unchanged") == "1":
            return None
        self.manifest_digest = reply.headers.get("Sentinel-Digest")
        return codec.decode(reply.data)

    def apply_manifest(self, manifest: list[dict]) -> None:
        self.records.put_summaries(manifest, self.hub_id)
        self._rebuild_queue(manifest)

    def _rebuild_queue(self, manifest: list[dict]) -> None:
        now = self.clock.now()
        items: list[WantItem] = []
        for compact in manifest:
            # Generic fields only: item id, deadline, consequence, records.
            deadline = dt.datetime.fromtimestamp(compact["dl"], dt.UTC)
            consequence = Consequence(int(compact["q"]))
            cdms = compact.get("c", [])
            for index, (sha16, size, created) in enumerate(cdms):
                if self.records.has(sha16):
                    continue
                latest = index == len(cdms) - 1
                if not latest:
                    klass = PriorityClass.P4_BULK
                elif consequence >= Consequence.SERIOUS and (deadline - now).total_seconds() <= self.urgent_window_s:
                    klass = PriorityClass.P1_URGENT
                else:
                    klass = PriorityClass.P2_ROUTINE
                items.append(
                    WantItem(
                        compact["e"], sha16, int(size), int(created), latest,
                        TriageKey(compact["e"], klass, deadline, consequence),
                    )
                )
        if self.mode == "fifo":
            items.sort(key=lambda i: (i.created, i.sha16))
        else:
            by_key = {id(i.key): i for i in items}
            items = [by_key[id(k)] for k in order([i.key for i in items])]
        self.queue = items

    # --------------------------------------------------------------- full CDMs
    async def pull(self, budget_s: float | None = None) -> int:
        """Fetch queued CDMs in order. Returns how many arrived."""
        budget_s = budget_s if budget_s is not None else max(self.interval_s * 5, 10.0)
        started = time.monotonic()
        fetched = 0
        bytes_ahead = 0
        now = self.clock.now()
        for item in self.queue:
            if item.status in ("ARRIVED",):
                continue
            eta_wall = self.link.eta_s(bytes_ahead + item.size)
            item.eta_s = None if eta_wall is None else round(eta_wall, 1)
            if self.mode == "edf" and item.latest and eta_wall is not None and item.key.deadline is not None:
                seconds_left = (item.key.deadline - now).total_seconds()
                if eta_wall * self.clock.scale > seconds_left:
                    item.status = "SUMMARY_ONLY"
                    self.summary_only.add(item.event_id)
                    continue
            if time.monotonic() - started > budget_s:
                break
            item.status = "FETCHING"
            await self._fetch(item)
            fetched += 1
            bytes_ahead = 0
        self.queue = [i for i in self.queue if i.status != "ARRIVED"]
        return fetched

    async def _fetch(self, item: WantItem) -> None:
        request = codec.encode({"sha": item.sha16, "from": self.node_id})
        t0 = time.monotonic()
        reply = await self.bus.request(
            subjects.sync_fetch(self.hub_id), request, timeout=self._timeout(item.size)
        )
        elapsed = time.monotonic() - t0
        self.link.observe_success(elapsed, len(reply.data), elapsed)
        if reply.headers.get("Sentinel-Error"):
            item.status = "QUEUED"
            return
        outcome = await self.records.ingest(
            reply.data,
            f"sync:{self.hub_id}",
            reply.headers.get("Sentinel-Data-Class", "REAL"),
            reply.headers.get("Sentinel-Event-Id"),
        )
        hash_ok = outcome["sha256"] == reply.headers.get("Sentinel-Sha256", outcome["sha256"])
        item.status = "ARRIVED"
        self.summary_only.discard(item.event_id)
        arrival = {
            "event_id": item.event_id,
            "sha": item.sha16,
            "class": item.key.klass.name,
            "latest": item.latest,
            "bytes": len(reply.data),
            "wall_s": round(time.monotonic() - self.started_wall, 2),
            "node_time": self.clock.now().isoformat(),
            "deadline": None if item.key.deadline is None else item.key.deadline.isoformat(),
            "hash_ok": hash_ok,
            "status": outcome["status"],
            "verification": outcome.get("verification"),
        }
        self.arrivals.append(arrival)
        await self._publish("sync.arrival", arrival)

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        now = self.clock.now()
        return {
            "mode": self.mode,
            "hub_id": self.hub_id,
            "link": self.link.snapshot(),
            "queue": [i.view(now) for i in self.queue],
            "arrivals": self.arrivals[-50:],
            "arrivals_total": len(self.arrivals),
            "summary_only": sorted(self.summary_only),
            "last_cycle": self.last_cycle,
        }

