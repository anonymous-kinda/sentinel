"""The conjunction module's side of the sync interface (sync/records.py)."""

from __future__ import annotations

from ..obs import get_logger
from .service import ConjunctionService
from .summaries import disagreements, summary_problem

log = get_logger(__name__)


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
        now = self.service.clock.now()
        for compact in summaries:
            problem = summary_problem(compact, now, self.service.policy)
            if problem is not None:
                event_id = compact.get("e") if isinstance(compact, dict) else None
                log.warning("Hub summary rejected", origin=origin, event_id=str(event_id)[:80], reason=problem)
                continue
            self.service.store.put_remote_summary(compact["e"], compact, origin, now.isoformat())

    async def ingest(self, raw: bytes, source: str, data_class: str, item_id: str | None) -> dict:
        result = await self.service.ingest(raw, source, data_class, event_id=item_id)
        verification = None
        if result.event_id:
            summary = self.service.event_summary(result.event_id)
            remote = self.service.store.remote_summaries().get(result.event_id)
            verification = self.service._verification(summary, remote)
            if verification == "MISMATCH" and remote is not None and summary["latest_cdm_sha256"] == result.sha256:
                log.warning(
                    "Hub assertion not reproduced",
                    event_id=result.event_id,
                    origin=remote.get("_origin"),
                    sha256=result.sha256,
                    fields=disagreements(summary, remote),
                )
        return {"status": result.status, "sha256": result.sha256, "verification": verification}
