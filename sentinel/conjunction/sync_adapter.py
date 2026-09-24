"""The conjunction module's side of the sync interface (sync/records.py)."""

from __future__ import annotations

from .service import ConjunctionService


class ConjunctionRecords:
    def __init__(self, service: ConjunctionService):
        self.service = service

    def manifest(self) -> list[dict]:
        return self.service.manifest()

    def get(self, sha16: str) -> tuple[bytes, dict[str, str]] | None:
        row = self.service.store.cdm_by_prefix(sha16)
        if row is None:
            return None
        return row.raw, {
            "Nats-Msg-Id": row.sha256,
            "Sentinel-Sha256": row.sha256,
            "Sentinel-Event-Id": row.event_id,
            "Sentinel-Data-Class": row.data_class,
        }

    def has(self, sha16: str) -> bool:
        return self.service.store.has_cdm_prefix(sha16)

    def put_summaries(self, summaries: list[dict], origin: str) -> None:
        now = self.service.clock.now().isoformat()
        for compact in summaries:
            self.service.store.put_remote_summary(compact["e"], compact, origin, now)

    async def ingest(self, raw: bytes, source: str, data_class: str, item_id: str | None) -> dict:
        result = await self.service.ingest(raw, source, data_class, event_id=item_id)
        verification = None
        if result.event_id:
            summary = self.service.event_summary(result.event_id)
            remote = self.service.store.remote_summaries().get(result.event_id)
            verification = self.service._verification(summary, remote)
        return {"status": result.status, "sha256": result.sha256, "verification": verification}
