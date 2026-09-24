"""State-based CRDTs for operator-authored data (ADR-005).

Decisions, notes, triage status and thresholds are written concurrently at
nodes that may be out of contact for hours. They must merge without losing
anyone's work, whatever order - or how many times - updates arrive.

    DotContext   causal history: which writes a replica has seen
    SignedLog    grow-only log of immutable, Ed25519-signed decision entries
    MVMap        map of multi-value registers: concurrent writes are kept
                 and shown as a CONFLICT, never silently overwritten

Merge is commutative, associative and idempotent (tests/property), so the
transport may drop, duplicate and reorder freely. That is the DDIL link.
"""

from .dots import Dot, DotContext
from .log import Entry, IntegrityError, SignedLog
from .mvmap import MVMap
from .signing import NodeKey, TrustStore

__all__ = ["Dot", "DotContext", "Entry", "IntegrityError", "MVMap", "NodeKey", "SignedLog", "TrustStore"]
