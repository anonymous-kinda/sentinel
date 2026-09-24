"""Dots and causal contexts (Almeida, Shoker & Baquero, Delta State
Replicated Data Types, 2018).

A dot (node, seq) names one write. A DotContext records every dot a
replica has seen: a version vector for the contiguous prefix per node, plus
a "cloud" of dots seen out of order - which is exactly what a DDIL link
delivers.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypedDict

WireDot = list[str | int]  # [node, seq]


class WireContext(TypedDict):
    vv: dict[str, int]
    cloud: list[WireDot]


@dataclasses.dataclass(frozen=True, order=True)
class Dot:
    node: str
    seq: int

    def to_wire(self) -> WireDot:
        return [self.node, self.seq]

    @classmethod
    def from_wire(cls, value: Sequence[Any]) -> Dot:
        return cls(str(value[0]), int(value[1]))


class DotContext:
    def __init__(self, vv: dict[str, int] | None = None, cloud: Iterable[Dot] = ()):
        self.vv: dict[str, int] = dict(vv or {})
        self.cloud: set[Dot] = set(cloud)
        self.compact()

    def copy(self) -> DotContext:
        return DotContext(self.vv, self.cloud)

    def contains(self, dot: Dot) -> bool:
        return dot.seq <= self.vv.get(dot.node, 0) or dot in self.cloud

    def add(self, dot: Dot) -> None:
        if not self.contains(dot):
            self.cloud.add(dot)
            self.compact()

    def next_dot(self, node: str) -> Dot:
        dot = Dot(node, self.vv.get(node, 0) + 1)
        self.add(dot)
        return dot

    def merge(self, other: DotContext) -> None:
        for node, seq in other.vv.items():
            if seq > self.vv.get(node, 0):
                self.vv[node] = seq
        self.cloud |= other.cloud
        self.compact()

    def compact(self) -> None:
        """Fold cloud dots into the version vector where they are contiguous."""
        changed = True
        while changed:
            changed = False
            for dot in sorted(self.cloud):
                current = self.vv.get(dot.node, 0)
                if dot.seq == current + 1:
                    self.vv[dot.node] = dot.seq
                    self.cloud.discard(dot)
                    changed = True
                elif dot.seq <= current:
                    self.cloud.discard(dot)
                    changed = True

    def dots(self) -> set[Dot]:
        out = set(self.cloud)
        for node, seq in self.vv.items():
            out.update(Dot(node, i) for i in range(1, seq + 1))
        return out

    def to_wire(self) -> WireContext:
        return {"vv": dict(sorted(self.vv.items())), "cloud": sorted(d.to_wire() for d in self.cloud)}

    @classmethod
    def from_wire(cls, value: Mapping[str, Any]) -> DotContext:
        return cls(value.get("vv", {}), (Dot.from_wire(d) for d in value.get("cloud", [])))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, DotContext) and self.vv == other.vv and self.cloud == other.cloud

    def __repr__(self) -> str:
        return f"DotContext(vv={self.vv}, cloud={sorted(self.cloud)})"
