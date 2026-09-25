"""Edge side: pull what matters most, first, over whatever link exists.

One cycle:

  1. Operator data (P0). One request carries this node's CRDT contexts and
     what the hub was last known to lack; the reply carries what this node
     lacks. Each way is held to a budget (what the link moves in
     OPS_BUDGET_S), so a backlog drains over several cycles and never
     starves the steps below. State-based: a lost reply just means the
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
     with what the hub asserted (VERIFIED / MISMATCH). A reply whose bytes
     are not the record asked for, or that its module cannot ingest, is
     refused and retried with back-off; the records behind it still come.

Mode "fifo" replaces step 3's order with hub arrival order and turns
admission control off: the same transport and the same bytes, used as the
measured baseline in the LIMITED scenario.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import hashlib
import json
import re
import time
from typing import Any

from ..bus import Bus, Msg, NoResponders, RequestTimeout, subjects
from ..clock import Clock
from ..crdt import codec
from ..linkstate import LinkMonitor, LinkState
from ..obs import get_logger
from ..triage import Consequence, PriorityClass, TriageKey, order
from .operator_data import OperatorData
from .records import ReferenceRecords

log = get_logger(__name__)

LINK_ERRORS = (RequestTimeout, NoResponders, ConnectionError, OSError)
RETRY_MAX_PULLS = 32        # the most pulls a refused record sits out
MANIFEST_MIN_BYTES = 4000   # the manifest wait is sized for at least this
MANIFEST_MAX_BYTES = 256 * 1024     # and for at most this, however many were lost
OPS_BUDGET_S = 10.0         # link time one exchange may spend on operator data, each way
OPS_BUDGET_MAX_BYTES = 256_000
OPS_REPLY_OVERHEAD_BYTES = 2000     # the hub's contexts and counts around its payload
# What reading a summary sync cannot read raises. Each is skipped on its own.
MALFORMED = (TypeError, ValueError, KeyError, OverflowError)
_SHA16 = re.compile(r"[0-9a-f]{16}")


@dataclasses.dataclass(frozen=True)
class SummaryFields:
    """The four generic fields sync reads from one summary, checked."""

    item_id: str
    deadline: dt.datetime
    consequence: Consequence
    records: list[tuple[str, int, int]]         # (sha16, bytes, created epoch), oldest first


def read_summary(compact: Any) -> SummaryFields:
    """Read a summary's generic fields as docs/icd/sync-envelope.md defines
    them. Raises one of MALFORMED if sync cannot."""
    if not isinstance(compact, dict):
        raise TypeError("summary is not a map")
    item_id = compact["e"]
    if not isinstance(item_id, str) or not item_id:
        raise TypeError("item id is not a string")
    deadline = dt.datetime.fromtimestamp(compact["dl"], dt.UTC)
    consequence = Consequence(int(compact["q"]))
    records = [_read_record(entry) for entry in compact.get("c", [])]
    return SummaryFields(item_id, deadline, consequence, records)


def _read_record(entry: Any) -> tuple[str, int, int]:
    sha16, size, created = entry
    if not isinstance(sha16, str) or not _SHA16.fullmatch(sha16):
        raise ValueError("record name is not 16 hex digits")
    if int(size) < 0:
        raise ValueError("record size is negative")
    return sha16, int(size), int(created)


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

    def view(self, now: dt.datetime) -> dict[str, Any]:
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


def _is_the_record_asked_for(item: WantItem, reply: Msg) -> bool:
    """Whether a fetch reply's bytes are the record the manifest named.

    Their sha256 must begin with the sha16 the edge asked for and equal the
    hub's Sentinel-Sha256. A missing header is not a match.
    """
    sha256 = hashlib.sha256(reply.data).hexdigest()
    return sha256.startswith(item.sha16) and reply.headers.get("Sentinel-Sha256") == sha256


class RetryBackoff:
    """When a refused record may be asked for again, counted in pulls.

    It sits out 1 pull, then 2, 4 ... up to `max_pulls`: a fault in transit
    is retried on the next pull, but a record that keeps failing never costs
    a thin link a round trip every cycle. Arrival clears it.
    """

    def __init__(self, max_pulls: int = RETRY_MAX_PULLS):
        self.max_pulls = max_pulls
        self._waits: dict[str, tuple[int, int]] = {}      # sha16 -> (pulls sat out, next pull allowed)

    def failed(self, sha16: str, pull: int) -> int:
        """Record a failure at `pull`. Returns how many pulls the record sits out."""
        previous = self._waits.get(sha16)
        wait = 1 if previous is None else min(2 * previous[0], self.max_pulls)
        self._waits[sha16] = (wait, pull + wait)
        return wait

    def due(self, sha16: str, pull: int) -> bool:
        waiting = self._waits.get(sha16)
        return waiting is None or pull >= waiting[1]

    def clear(self, sha16: str) -> None:
        self._waits.pop(sha16, None)

    def retain(self, sha16s: set[str]) -> None:
        """Forget records no longer wanted, so a hub cannot grow this without bound."""
        self._waits = {sha: waiting for sha, waiting in self._waits.items() if sha in sha16s}


class SyncAgent:
    def __init__(
        self,
        bus: Bus,
        records: ReferenceRecords,
        ops: OperatorData,
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
        self.arrivals: list[dict[str, Any]] = []
        self.summary_only: set[str] = set()
        self.manifest_digest: str | None = None
        self._received_digest: str | None = None
        self._manifest_bytes = MANIFEST_MIN_BYTES      # the size of the manifest last received
        self._manifests_lost = 0                       # manifest timeouts in a row
        self.last_cycle: dict[str, Any] = {}
        self.started_wall = time.monotonic()
        self._last_state: LinkState | None = None
        self._pulls = 0
        self._backoff = RetryBackoff()

    # ------------------------------------------------------------------ helpers
    def _rate(self) -> float:
        """The measured link rate in B/s: 1000 until one is measured, never below 400."""
        return max(self.link.rate_bytes_per_s or 1000.0, 400.0)

    def _timeout(self, expected_bytes: int) -> float:
        return 6.0 + 1.5 * expected_bytes / self._rate()

    def _ops_budget(self) -> int:
        """Bytes of operator data one exchange carries each way: what the link
        moves in OPS_BUDGET_S, so a backlog drains over several cycles and the
        manifest and records still get the link in each."""
        return int(min(self._rate() * OPS_BUDGET_S, OPS_BUDGET_MAX_BYTES))

    async def _publish(self, kind: str, payload: dict[str, Any]) -> None:
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
    async def exchange_ops(self) -> dict[str, Any]:
        budget = self._ops_budget()
        peer = self.ops.peer_contexts(self.hub_id)
        push = self.ops.payload_for(peer["log_ctx"], peer["mv_ctx"], budget)
        request = codec.encode({"from": self.node_id, **self.ops.contexts(), "push": push, "budget": budget})
        t0 = time.monotonic()
        reply_msg = await self.bus.request(
            subjects.ops_exchange(self.hub_id), request,
            timeout=self._timeout(len(request) + budget + OPS_REPLY_OVERHEAD_BYTES),
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
    async def fetch_manifest(self) -> list[dict[str, Any]] | None:
        request = codec.encode({"from": self.node_id, "known": self.manifest_digest})
        expected_bytes = self._manifest_expected_bytes()
        t0 = time.monotonic()
        try:
            reply = await self.bus.request(
                subjects.sync_manifest(self.hub_id), request, timeout=self._timeout(expected_bytes)
            )
        except RequestTimeout:
            self._manifests_lost += 1
            log.info("Manifest request timed out", hub_id=self.hub_id, expected_bytes=expected_bytes,
                     next_expected_bytes=self._manifest_expected_bytes())
            raise
        rtt = time.monotonic() - t0
        self.link.observe_success(rtt, len(reply.data), rtt)
        self._manifests_lost = 0
        if reply.headers.get("Sentinel-Unchanged") == "1":
            return None
        self._manifest_bytes = max(len(reply.data), MANIFEST_MIN_BYTES)
        self._received_digest = reply.headers.get("Sentinel-Digest")
        manifest: list[dict[str, Any]] = codec.decode(reply.data)
        return manifest

    def _manifest_expected_bytes(self) -> int:
        """Size the manifest wait from the last one received, doubled for each
        timeout in a row: a manifest that outgrew the wait still gets through
        a thin link, and one that is merely lost does not stall the cycle for
        long."""
        return min(self._manifest_bytes << self._manifests_lost, MANIFEST_MAX_BYTES)

    def apply_manifest(self, manifest: list[dict[str, Any]]) -> None:
        """Store the hub's summaries and rebuild the want-list. Only then is the
        manifest's digest sent back as `known`: one that failed to apply is
        fetched again, not reported unchanged."""
        self.records.put_summaries(manifest, self.hub_id)
        self._rebuild_queue(manifest)
        self.manifest_digest = self._received_digest

    def _rebuild_queue(self, manifest: list[dict[str, Any]]) -> None:
        now = self.clock.now()
        items: list[WantItem] = []
        for compact in manifest:
            try:
                fields = read_summary(compact)
            except MALFORMED as exc:
                item_id = compact.get("e") if isinstance(compact, dict) else None
                log.warning(
                    "Manifest entry skipped",
                    hub_id=self.hub_id, item_id=str(item_id)[:80], error=type(exc).__name__, detail=str(exc)[:200],
                )
                continue
            items += self._wanted(fields, now)
        if self.mode == "fifo":
            items.sort(key=lambda i: (i.created, i.sha16))
        else:
            by_key = {id(i.key): i for i in items}
            items = [by_key[id(k)] for k in order([i.key for i in items])]
        self.queue = items
        self._backoff.retain({i.sha16 for i in items})

    def _wanted(self, fields: SummaryFields, now: dt.datetime) -> list[WantItem]:
        """The records a summary names that this node lacks, each in its priority class."""
        items: list[WantItem] = []
        for index, (sha16, size, created) in enumerate(fields.records):
            if self.records.has(sha16):
                continue
            latest = index == len(fields.records) - 1
            if not latest:
                klass = PriorityClass.P4_BULK
            elif (
                fields.consequence >= Consequence.SERIOUS
                and (fields.deadline - now).total_seconds() <= self.urgent_window_s
            ):
                klass = PriorityClass.P1_URGENT
            else:
                klass = PriorityClass.P2_ROUTINE
            key = TriageKey(fields.item_id, klass, fields.deadline, fields.consequence)
            items.append(WantItem(fields.item_id, sha16, size, created, latest, key))
        return items

    # --------------------------------------------------------------- full CDMs
    async def pull(self, budget_s: float | None = None) -> int:
        """Fetch queued CDMs in order. Returns how many arrived."""
        budget_s = budget_s if budget_s is not None else max(self.interval_s * 5, 10.0)
        started = time.monotonic()
        fetched = 0
        self._pulls += 1
        for item in self.queue:
            if item.status in ("ARRIVED",) or not self._backoff.due(item.sha16, self._pulls):
                continue
            eta_wall = self.link.eta_s(item.size)
            item.eta_s = None if eta_wall is None else round(eta_wall, 1)
            if self.mode == "edf" and item.latest and eta_wall is not None and item.key.deadline is not None:
                # Read the clock per record: the fetches ahead of it spent node time.
                seconds_left = (item.key.deadline - self.clock.now()).total_seconds()
                if eta_wall * self.clock.scale > seconds_left:
                    item.status = "SUMMARY_ONLY"
                    self.summary_only.add(item.event_id)
                    continue
            if time.monotonic() - started > budget_s:
                break
            item.status = "FETCHING"
            await self._fetch(item)
            fetched += 1
        self.queue = [i for i in self.queue if i.status != "ARRIVED"]
        return fetched

    async def _fetch(self, item: WantItem) -> None:
        reply = await self._request_record(item)
        if reply.headers.get("Sentinel-Error"):
            item.status = "QUEUED"
            return
        if not _is_the_record_asked_for(item, reply):
            self._refuse(item, "hash_mismatch", hash_ok=False, hub_sha256=reply.headers.get("Sentinel-Sha256"))
            return
        # The manifest named the item; the header, when sent, must agree.
        hub_item_id = reply.headers.get("Sentinel-Event-Id", item.event_id)
        if hub_item_id != item.event_id:
            self._refuse(item, "item_id_mismatch", hub_item_id=hub_item_id[:80])
            return
        try:
            outcome = await self.records.ingest(
                reply.data, f"sync:{self.hub_id}", reply.headers.get("Sentinel-Data-Class", "REAL"), item.event_id
            )
        except Exception:  # noqa: BLE001 - one record's failure must not stop the records behind it
            wait = self._put_back(item)
            log.exception("Sync record ingest failed", retry_in_pulls=wait, **self._about(item))
            return
        await self._arrived(item, reply, outcome)

    async def _request_record(self, item: WantItem) -> Msg:
        request = codec.encode({"sha": item.sha16, "from": self.node_id})
        t0 = time.monotonic()
        reply = await self.bus.request(subjects.sync_fetch(self.hub_id), request, timeout=self._timeout(item.size))
        elapsed = time.monotonic() - t0
        self.link.observe_success(elapsed, len(reply.data), elapsed)
        return reply

    async def _arrived(self, item: WantItem, reply: Msg, outcome: dict[str, Any]) -> None:
        item.status = "ARRIVED"
        self._backoff.clear(item.sha16)
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
            "hash_ok": True,
            "status": outcome["status"],
            "verification": outcome.get("verification"),
        }
        self.arrivals.append(arrival)
        await self._publish("sync.arrival", arrival)

    def _refuse(self, item: WantItem, reason: str, **fields: Any) -> None:
        """Put back a record whose reply the edge will not admit, and say why."""
        wait = self._put_back(item)
        log.warning("Sync record refused", reason=reason, retry_in_pulls=wait, **self._about(item), **fields)

    def _put_back(self, item: WantItem) -> int:
        """Re-queue a record the edge could not admit. Returns the pulls it sits out."""
        item.status = "QUEUED"
        return self._backoff.failed(item.sha16, self._pulls)

    def _about(self, item: WantItem) -> dict[str, Any]:
        """Log fields naming a record. The item id is the hub's, so it is cut short."""
        return {"hub_id": self.hub_id, "item_id": item.event_id[:80], "sha16": item.sha16}

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
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

