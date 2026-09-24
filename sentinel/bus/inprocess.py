"""In-memory bus for single-process deployment and tests."""

from __future__ import annotations

import asyncio
import logging

from .base import Handler, Msg, subject_matches

log = logging.getLogger(__name__)


class _Sub:
    def __init__(self, bus: InProcessBus, pattern: str, handler: Handler):
        self.bus = bus
        self.pattern = pattern
        self.handler = handler

    async def unsubscribe(self) -> None:
        if self in self.bus._subs:
            self.bus._subs.remove(self)


class InProcessBus:
    """Delivers each message to every matching subscriber, in order.

    Delivery is awaited, so a publisher knows its subscribers have seen the
    message when publish() returns. A failing handler is logged and does not
    stop delivery to the others: one broken consumer must not blind the rest.
    """

    def __init__(self) -> None:
        self._subs: list[_Sub] = []
        self.failures = 0

    async def publish(self, subject: str, data: bytes, headers: dict[str, str] | None = None) -> None:
        msg = Msg(subject, data, dict(headers or {}))
        for sub in list(self._subs):
            if subject_matches(sub.pattern, subject):
                try:
                    await sub.handler(msg)
                except Exception:  # noqa: BLE001 - isolate subscribers
                    self.failures += 1
                    log.exception("bus handler for %s failed on %s", sub.pattern, subject)

    async def subscribe(self, subject: str, handler: Handler) -> _Sub:
        sub = _Sub(self, subject, handler)
        self._subs.append(sub)
        return sub

    async def close(self) -> None:
        self._subs.clear()
        await asyncio.sleep(0)
