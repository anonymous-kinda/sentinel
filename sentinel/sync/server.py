"""Hub side: answer manifest, fetch and operator-data exchange requests."""

from __future__ import annotations

from ..bus import Bus, Msg, subjects
from ..crdt import codec
from .operator_data import OperatorData
from .records import ReferenceRecords


class SyncServer:
    def __init__(self, bus: Bus, records: ReferenceRecords, ops: OperatorData, node_id: str):
        self.bus = bus
        self.records = records
        self.ops = ops
        self.node_id = node_id
        self.requests = {"manifest": 0, "fetch": 0, "ops": 0}

    async def start(self) -> None:
        await self.bus.serve(subjects.sync_manifest(self.node_id), self._manifest)
        await self.bus.serve(subjects.sync_fetch(self.node_id), self._fetch)
        await self.bus.serve(subjects.ops_exchange(self.node_id), self._ops)

    async def _manifest(self, msg: Msg) -> tuple[bytes, dict[str, str]]:
        self.requests["manifest"] += 1
        request = codec.decode(msg.data) if msg.data else {}
        manifest = self.records.manifest()
        body = codec.encode(manifest)
        digest = codec.digest(manifest)
        if request.get("known") == digest:
            # Nothing changed since the edge last asked: send nothing but the fact.
            return b"", {"Sentinel-Unchanged": "1", "Sentinel-Digest": digest}
        return body, {"Sentinel-Digest": digest, "Sentinel-Schema": "sentinel.manifest/1"}

    async def _fetch(self, msg: Msg) -> tuple[bytes, dict[str, str]]:
        self.requests["fetch"] += 1
        request = codec.decode(msg.data)
        found = self.records.get(str(request["sha"]))
        if found is None:
            return b"", {"Sentinel-Error": "not-found"}
        # The original bytes, untouched: the edge checks the hash end to end.
        raw, headers = found
        return raw, {**headers, "Sentinel-Kind": "record.full"}

    async def _ops(self, msg: Msg) -> tuple[bytes, dict[str, str]]:
        self.requests["ops"] += 1
        request = codec.decode(msg.data)
        merged = await self.ops.merge_payload(request.get("push", {}))
        pull = self.ops.payload_for(request["log_ctx"], request["mv_ctx"])
        reply = {"pull": pull, "ctx": self.ops.contexts(), "merged": merged}
        return codec.encode(reply), {"Sentinel-Kind": "ops.exchange"}
