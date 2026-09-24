"""The interface between the sync layer and any mission module.

Sync moves *records* (opaque bytes with a content hash) described by
*summaries* (a small dict with generic triage fields). It never learns what
a record means. A mission module plugs in by implementing this protocol;
the conjunction module does it in conjunction/sync_adapter.py, and the
M3 pass module can do the same without a line of sync changing.

Summary fields the sync layer reads:
    e   item id                       dl  deadline (epoch seconds)
    q   consequence (0-3)             c   [[sha16, bytes, created_epoch], ...]
"""

from __future__ import annotations

from typing import Any, Protocol


class ReferenceRecords(Protocol):
    def manifest(self) -> list[dict[str, Any]]: ...

    def get(self, sha16: str) -> tuple[bytes, dict[str, str]] | None:
        """Raw record bytes plus headers (Sentinel-Event-Id, -Data-Class, -Sha256)."""
        ...

    def has(self, sha16: str) -> bool: ...

    def put_summaries(self, summaries: list[dict[str, Any]], origin: str) -> None: ...

    async def ingest(self, raw: bytes, source: str, data_class: str, item_id: str | None) -> dict[str, Any]:
        """Admit a fetched record. Returns {status, sha256, verification}."""
        ...
