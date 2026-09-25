"""What an edge says it fetched, read from its own `GET /api/sync`.

Shared by the scenarios that count what crossed the link: DENIED (the
catch-up after a reconnect), LIMITED (the records each run moved) and
OPSEC (the element sets that reached the edge).
"""

from __future__ import annotations

import hashlib


class SyncLedger:
    """Every record an edge says it fetched, from its own `GET /api/sync`.

    The edge counts every arrival since it started but shows only the most
    recent ones. Fed each status read in turn, the ledger appends the
    arrivals it has not seen yet. Any that scrolled out of the shown window
    between two reads are counted in `unseen`, never guessed at. A ledger
    started with `after` (the edge's running total at that moment) keeps
    only what arrives later."""

    def __init__(self, after: int = 0) -> None:
        self.arrivals: list[dict] = []
        self.unseen = 0
        self.after = after

    def record(self, status: dict) -> None:
        new = status["arrivals_total"] - self.after - len(self.arrivals) - self.unseen
        if new <= 0:
            return
        window = status["arrivals"]
        shown = min(new, len(window))
        self.arrivals += window[len(window) - shown :]
        self.unseen += new - shown

    def items(self, prefix: str) -> set[str]:
        """The distinct item ids fetched whose id starts with `prefix`."""
        return {a["event_id"] for a in self.arrivals if a["event_id"].startswith(prefix)}

    def digest(self) -> str:
        """One hash of the set of records fetched, whatever the order: equal
        digests mean two edges fetched the identical records."""
        return hashlib.sha256("\n".join(sorted(a["sha"] for a in self.arrivals)).encode()).hexdigest()[:16]
