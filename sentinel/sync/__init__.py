"""Hub-to-edge synchronisation (ADR-006, ADR-008).

Reference data (CDMs) flows hub -> edge through a priority pull: summaries
first, then full messages earliest-deadline-first. Operator data (decision
log, annotations) flows both ways by CRDT anti-entropy. Both run over
request/reply on the bus, so the same code works over NATS leaf nodes,
in-process for tests, and - with a file transport - over removable media.
"""

from .agent import SyncAgent
from .server import SyncServer

__all__ = ["SyncAgent", "SyncServer"]
