"""The internal event bus (ADR-004).

Modules talk through subjects, never through each other's objects. In a
single process the bus is in-memory; at the edge and in the cloud it is
NATS JetStream. Swapping one for the other changes no module code, which is
the practical meaning of "modular monolith that can be decomposed".
"""

from .base import (
    Bus,
    Handler,
    Msg,
    NoResponders,
    RequestTimeout,
    Responder,
    Subscription,
    subject_matches,
)
from .inprocess import InProcessBus, LateBus

__all__ = [
    "Bus",
    "Handler",
    "InProcessBus",
    "LateBus",
    "Msg",
    "NoResponders",
    "RequestTimeout",
    "Responder",
    "Subscription",
    "subject_matches",
]
