"""Several mission modules behind one sync interface (sync/records.py).

The sync layer takes a single ReferenceRecords. This composite routes by
item-id prefix so each mission module plugs in beside the others - and
lives here, in the node's assembly layer, so sentinel/sync never changes
when a module is added.
"""

from __future__ import annotations


class CompositeRecords:
    def __init__(self, default, by_prefix: dict):
        """`default` serves item ids with no registered prefix (conjunction
        events); `by_prefix` maps an item-id prefix to its module's records."""
        self._default = default
        self._by_prefix = dict(by_prefix)
        self._all = [default, *self._by_prefix.values()]

    def _for(self, item_id: str | None):
        for prefix, records in self._by_prefix.items():
            if item_id and item_id.startswith(prefix):
                return records
        return self._default

    def manifest(self) -> list[dict]:
        return [entry for records in self._all for entry in records.manifest()]

    def get(self, sha16: str):
        return next((found for records in self._all if (found := records.get(sha16)) is not None), None)

    def has(self, sha16: str) -> bool:
        return any(records.has(sha16) for records in self._all)

    def put_summaries(self, summaries: list[dict], origin: str) -> None:
        """A summary with no readable item id goes to the default module,
        which rejects and logs what it cannot show."""
        grouped: dict[int, list[dict]] = {}
        for summary in summaries:
            item_id = summary.get("e") if isinstance(summary, dict) else None
            grouped.setdefault(id(self._for(item_id if isinstance(item_id, str) else None)), []).append(summary)
        for records in self._all:
            records.put_summaries(grouped.get(id(records), []), origin)

    async def ingest(self, raw: bytes, source: str, data_class: str, item_id: str | None) -> dict:
        return await self._for(item_id).ingest(raw, source, data_class, item_id)
