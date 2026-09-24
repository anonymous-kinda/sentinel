"""Bus protocol and NATS-compatible subject matching."""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Protocol


@dataclasses.dataclass(frozen=True)
class Msg:
    subject: str
    data: bytes
    headers: dict[str, str] = dataclasses.field(default_factory=dict)


Handler = Callable[[Msg], Awaitable[None]]


class Subscription(Protocol):
    async def unsubscribe(self) -> None: ...


class Bus(Protocol):
    async def publish(self, subject: str, data: bytes, headers: dict[str, str] | None = None) -> None: ...

    async def subscribe(self, subject: str, handler: Handler) -> Subscription: ...

    async def close(self) -> None: ...


def subject_matches(pattern: str, subject: str) -> bool:
    """NATS semantics: tokens split on '.', '*' matches one token, '>' matches
    one or more trailing tokens."""
    p_tokens = pattern.split(".")
    s_tokens = subject.split(".")
    for i, p in enumerate(p_tokens):
        if p == ">":
            return len(s_tokens) > i
        if i >= len(s_tokens):
            return False
        if p != "*" and p != s_tokens[i]:
            return False
    return len(p_tokens) == len(s_tokens)
