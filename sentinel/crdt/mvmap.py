"""A map of multi-value registers (delta-state, dotted).

Each key holds a register: the values currently visible, each tagged with
the dot that wrote it, plus the causal context of every write to that key.
A write replaces the values its author could see. Concurrent writes -
two nodes changing the same field while partitioned - are both kept.
Reading more than one value is a CONFLICT, and the console shows every
value with who wrote it and where. Nothing is decided by timestamp.

Join of two register states (store A, ctx A) and (store B, ctx B):

    keep (d, v) from A  if d in B.store or d not in B.ctx
    keep (d, v) from B  if d in A.store or d not in A.ctx
    ctx = A.ctx U B.ctx

A dot one side has seen but no longer stores was overwritten there, so it
is dropped. A dot one side has never seen survives.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any, TypedDict

from . import codec
from .dots import Dot, DotContext, WireContext


class WireRegister(TypedDict):
    store: list[list[Any]]  # [[wire dot, value], ...]
    ctx: WireContext


@dataclasses.dataclass
class Register:
    store: dict[Dot, Any] = dataclasses.field(default_factory=dict)
    ctx: DotContext = dataclasses.field(default_factory=DotContext)

    def to_wire(self) -> WireRegister:
        return {
            "store": [[d.to_wire(), v] for d, v in sorted(self.store.items())],
            "ctx": self.ctx.to_wire(),
        }

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> Register:
        return cls(
            {Dot.from_wire(d): v for d, v in value["store"]},
            DotContext.from_wire(value["ctx"]),
        )


class MVMap:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.registers: dict[str, Register] = {}
        self.ctx = DotContext()      # every dot seen in any key

    def write(self, key: str, value: Any) -> Dot:
        dot = self.ctx.next_dot(self.node_id)
        reg = self.registers.setdefault(key, Register())
        for old in reg.store:
            reg.ctx.add(old)
        reg.store = {dot: value}
        reg.ctx.add(dot)
        return dot

    def read(self, key: str) -> list[tuple[Dot, Any]]:
        reg = self.registers.get(key)
        return [] if reg is None else sorted(reg.store.items())

    def conflicted(self, key: str) -> bool:
        return len(self.read(key)) > 1

    def merge_register(self, key: str, other: Register) -> bool:
        """Join one register state in. Returns True if anything changed."""
        mine = self.registers.get(key, Register())
        store = {
            d: v for d, v in mine.store.items() if d in other.store or not other.ctx.contains(d)
        }
        for d, v in other.store.items():
            if d in mine.store or not mine.ctx.contains(d):
                store[d] = v
        ctx = mine.ctx.copy()
        ctx.merge(other.ctx)
        changed = store.keys() != mine.store.keys() or ctx != mine.ctx
        self.registers[key] = Register(store, ctx)
        self.ctx.merge(other.ctx)
        return changed

    def missing_for(self, peer: DotContext) -> dict[str, Register]:
        """Every register holding a write the peer has not seen."""
        return {key: reg for key, reg in self.registers.items() if not peer.covers(reg.ctx)}

    def state_digest(self) -> str:
        return codec.digest(
            sorted((k, [[d.to_wire(), v] for d, v in sorted(r.store.items())]) for k, r in self.registers.items())
        )
