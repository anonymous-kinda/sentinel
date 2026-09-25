"""The interface between the sync layer and the operator-data replica.

Operator data (the signed decision log and the annotation registers) flows
both ways by state-based anti-entropy (ADR-005). Sync carries the exchange;
the replica (sentinel.ops.OpsService) owns the CRDTs. This is everything
sync asks of it. Contexts and payloads are CRDT wire data, passed through
opaque: sync never reads inside them.
"""

from __future__ import annotations

from typing import Any, Protocol


class OperatorData(Protocol):
    def contexts(self) -> dict[str, Any]:
        """This replica's causal contexts: {log_ctx, mv_ctx}."""
        ...

    def peer_contexts(self, peer: str) -> dict[str, Any]:
        """The contexts a peer was last known to hold."""
        ...

    def remember_peer(self, peer: str, contexts: dict[str, Any]) -> None: ...

    def payload_for(
        self, log_ctx: dict[str, Any], mv_ctx: dict[str, Any], budget_bytes: int | None = None
    ) -> dict[str, Any]:
        """What this replica holds that a peer with these contexts lacks: all of
        it, or with a budget the leading part whose encoding fits in it (always
        at least one item), taken in turns across authors so that none can
        starve the others. The rest goes in a later exchange."""
        ...

    async def merge_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Join a peer's payload in. Returns merge counts."""
        ...
