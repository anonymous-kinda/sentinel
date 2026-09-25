"""Grow-only log of signed, immutable decision entries.

State: a map from dot to entry. Merge: union. Two replicas that have seen
the same set of entries hold identical logs, whatever order the entries
arrived in, so display order is derived - (lamport, node, seq) - rather
than stored.

Integrity rules, in the spirit of "wrong raises, incomplete degrades":

  * An entry whose signature does not verify under the trust store, or
    whose author node is not trusted, is rejected before merge and recorded.
    Incomplete trust (an unknown node) degrades; nothing is lost silently.
  * The same dot arriving, validly signed, with a different digest can
    only happen through a bug in a trusted node or a stolen key. It raises
    IntegrityError: the replica stops rather than choose which history to
    believe. An unsigned forgery that reuses a dot is rejected like any other.
  * Each node's entries form a hash chain (prev = digest of that node's
    previous entry). A chain break where both links are present raises.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from typing import Any, TypedDict

from . import codec
from .dots import Dot, DotContext, WireDot
from .signing import NodeKey, TrustStore

KINDS = ("DECISION", "NOTE", "RESOLUTION", "AI_DRAFT_CONFIRMED")


class IntegrityError(RuntimeError):
    pass


class UnsignedEntry(TypedDict):
    """What an entry's signature covers."""

    dot: WireDot
    lamport: int
    wall_time: str
    kind: str
    event_ref: dict[str, Any]
    body: dict[str, Any]
    author: str
    prev: str | None


class WireEntry(UnsignedEntry):
    sig: str


class Rejection(TypedDict):
    dot: WireDot
    reason: str
    author: str


@dataclasses.dataclass(frozen=True)
class Entry:
    dot: Dot
    lamport: int
    wall_time: str
    kind: str
    event_ref: dict[str, Any]
    body: dict[str, Any]
    author: str
    prev: str | None
    sig: str = ""

    def unsigned(self) -> UnsignedEntry:
        return {
            "dot": self.dot.to_wire(),
            "lamport": self.lamport,
            "wall_time": self.wall_time,
            "kind": self.kind,
            "event_ref": self.event_ref,
            "body": self.body,
            "author": self.author,
            "prev": self.prev,
        }

    def to_wire(self) -> WireEntry:
        return {**self.unsigned(), "sig": self.sig}

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> Entry:
        return cls(
            dot=Dot.from_wire(value["dot"]),
            lamport=int(value["lamport"]),
            wall_time=str(value["wall_time"]),
            kind=str(value["kind"]),
            event_ref=dict(value["event_ref"]),
            body=dict(value["body"]),
            author=str(value["author"]),
            prev=value.get("prev"),
            sig=str(value["sig"]),
        )

    def digest(self) -> str:
        return codec.digest(self.to_wire())

    def signed_bytes(self) -> bytes:
        return codec.encode(self.unsigned())


class SignedLog:
    def __init__(self, node_id: str, key: NodeKey | None, trust: TrustStore):
        self.node_id = node_id
        self.key = key
        self.trust = trust
        self.entries: dict[Dot, Entry] = {}
        self.ctx = DotContext()
        self.lamport = 0
        self.rejected: list[Rejection] = []

    def append(
        self, kind: str, body: dict[str, Any], event_ref: dict[str, Any], author: str, wall_time: str
    ) -> Entry:
        if kind not in KINDS:
            raise ValueError(f"unknown entry kind {kind!r}")
        if self.key is None:
            raise RuntimeError("this replica has no signing key; it cannot author entries")
        dot = self.ctx.next_dot(self.node_id)
        prev_entry = self.entries.get(Dot(self.node_id, dot.seq - 1))
        self.lamport += 1
        entry = Entry(
            dot=dot,
            lamport=self.lamport,
            wall_time=wall_time,
            kind=kind,
            event_ref=event_ref,
            body=body,
            author=author,
            prev=None if prev_entry is None else prev_entry.digest(),
        )
        entry = dataclasses.replace(entry, sig=self.key.sign(entry.signed_bytes()).hex())
        self.entries[dot] = entry
        return entry

    def verify(self, entry: Entry) -> bool:
        try:
            signature = bytes.fromhex(entry.sig)
        except ValueError:
            return False  # not hex: no signature at all, so it cannot verify
        return self.trust.verify(entry.dot.node, entry.signed_bytes(), signature)

    def merge(self, incoming: Iterable[Entry]) -> list[Entry]:
        """Merge entries; return the ones that were new. Idempotent."""
        added = []
        for entry in incoming:
            existing = self.entries.get(entry.dot)
            if existing is not None and existing.digest() == entry.digest():
                continue  # already held, byte for byte
            # Verify before comparing: only a validly signed entry can make
            # the replica stop; a forgery that reuses a dot is rejected.
            if not self.verify(entry):
                self.rejected.append(
                    {"dot": entry.dot.to_wire(), "reason": "untrusted-or-bad-signature", "author": entry.author}
                )
                continue
            if existing is not None:
                raise IntegrityError(f"dot {entry.dot} arrived with a different digest")
            self._check_chain(entry)
            self.entries[entry.dot] = entry
            self.ctx.add(entry.dot)
            self.lamport = max(self.lamport, entry.lamport)
            added.append(entry)
        return added

    def _check_chain(self, entry: Entry) -> None:
        before = self.entries.get(Dot(entry.dot.node, entry.dot.seq - 1))
        if before is not None and entry.prev != before.digest():
            raise IntegrityError(f"hash chain broken at {entry.dot}")
        after = self.entries.get(Dot(entry.dot.node, entry.dot.seq + 1))
        if after is not None and after.prev != entry.digest():
            raise IntegrityError(f"hash chain broken after {entry.dot}")

    def missing_for(self, peer: DotContext) -> list[Entry]:
        return [e for d, e in self.entries.items() if not peer.contains(d)]

    def ordered(self) -> list[Entry]:
        return sorted(self.entries.values(), key=lambda e: (e.lamport, e.dot.node, e.dot.seq))

    def state_digest(self) -> str:
        return codec.digest(sorted(e.digest() for e in self.entries.values()))
