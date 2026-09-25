"""Hub-to-edge synchronisation (ADR-006, ADR-008).

Reference data flows hub -> edge through a priority pull: summaries first,
then full records earliest-deadline-first. Operator data (decision log,
annotations) flows both ways by CRDT anti-entropy. Both run over
request/reply on the bus, so the same code works over NATS leaf nodes and
in-process for tests. There is no other transport: nothing carries sync
over removable media.
"""

from .agent import SyncAgent
from .server import SyncServer

__all__ = ["SyncAgent", "SyncServer"]
