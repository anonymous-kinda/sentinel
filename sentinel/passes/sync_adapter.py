"""The pass module's side of the sync interface (sync/records.py).

Element sets are public reference data the hub serves and edges pull
through the same priority agent as CDMs, without a line of sync changing.
Each is offered with the moment it goes stale as its deadline and ROUTINE
consequence, so on a thin link urgent conjunction records cross first.
The unit and its pass windows are not records: they never leave the node.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Awaitable, Callable

from ..clock import Clock
from ..triage import Consequence
from .element_store import ElementRejected, ElementStore
from .geometry import STALE_AFTER_DAYS

PREFIX = "omm:"


def item_id(norad_id: int) -> str:
    return f"{PREFIX}{norad_id}"


class ElementRecords:
    def __init__(
        self,
        store: ElementStore,
        clock: Clock,
        on_accepted: Callable[[], Awaitable[None]] | None = None,
        offered: Callable[[int], bool] | None = None,
    ):
        """`on_accepted` is awaited after a fetched element set changes the
        store, so the node can tell its console the pass inputs moved.
        `offered` limits which element sets go in the manifest (None: all):
        every record costs a round trip on a thin link."""
        self.store = store
        self.clock = clock
        self.remote: dict[str, dict] = {}
        self._on_accepted = on_accepted
        self._offered = offered or (lambda _norad_id: True)

    def manifest(self) -> list[dict]:
        out = []
        for record in self.store.records():
            if not self._offered(record.norad_id):
                continue
            stale_at = record.epoch + dt.timedelta(days=STALE_AFTER_DAYS)
            out.append(
                {
                    "e": item_id(record.norad_id),
                    "dl": int(stale_at.timestamp()),
                    "q": int(Consequence.ROUTINE),
                    "c": [[record.sha256[:16], len(record.raw), int(record.epoch.timestamp())]],
                }
            )
        return out

    def get(self, sha16: str) -> tuple[bytes, dict[str, str]] | None:
        record = self.store.by_sha_prefix(sha16)
        if record is None:
            return None
        return record.raw, {
            "Nats-Msg-Id": record.sha256,
            "Sentinel-Sha256": record.sha256,
            "Sentinel-Event-Id": item_id(record.norad_id),
            "Sentinel-Data-Class": "REAL",
        }

    def has(self, sha16: str) -> bool:
        return self.store.has_seen(sha16)

    def put_summaries(self, summaries: list[dict], origin: str) -> None:
        for summary in summaries:
            self.remote[summary["e"]] = {**summary, "_origin": origin}

    async def ingest(self, raw: bytes, source: str, data_class: str, item_id: str | None) -> dict:
        try:
            result = self.store.add(raw, source)
        except ElementRejected as exc:
            return {"status": "rejected", "code": exc.code, "sha256": hashlib.sha256(raw).hexdigest(), "verification": None}
        if result.status == "accepted" and self._on_accepted is not None:
            await self._on_accepted()
        return {"status": result.status, "sha256": result.sha256, "verification": None}
