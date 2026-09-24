"""In-memory bus for single-process deployment and tests."""

from __future__ import annotations

import asyncio

from ..obs import get_logger
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

log = get_logger(__name__)


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
        self._responders: dict[str, Responder] = {}
        self.failures = 0

    async def publish(self, subject: str, data: bytes, headers: dict[str, str] | None = None) -> None:
        msg = Msg(subject, data, dict(headers or {}))
        for sub in list(self._subs):
            if subject_matches(sub.pattern, subject):
                try:
                    await sub.handler(msg)
                except Exception:  # noqa: BLE001 - isolate subscribers
                    self.failures += 1
                    log.exception("Bus handler failed", pattern=sub.pattern, subject=subject)

    async def subscribe(self, subject: str, handler: Handler) -> _Sub:
        sub = _Sub(self, subject, handler)
        self._subs.append(sub)
        return sub

    async def request(
        self, subject: str, data: bytes, timeout: float, headers: dict[str, str] | None = None
    ) -> Msg:
        for pattern, responder in self._responders.items():
            if subject_matches(pattern, subject):
                try:
                    body, reply_headers = await asyncio.wait_for(
                        responder(Msg(subject, data, dict(headers or {}))), timeout
                    )
                except TimeoutError as exc:
                    raise RequestTimeout(subject) from exc
                return Msg(subject, body, reply_headers)
        raise NoResponders(subject)

    async def serve(self, subject: str, responder: Responder) -> _Sub:
        self._responders[subject] = responder

        async def _noop(_msg: Msg) -> None:
            return None

        sub = _Sub(self, subject, _noop)
        return sub

    async def close(self) -> None:
        self._subs.clear()
        self._responders.clear()
        await asyncio.sleep(0)


class LateBus:
    """A bus whose transport is chosen after construction.

    Services are built synchronously; NATS connects asynchronously at
    startup. LateBus lets services hold one reference while the node swaps
    the in-process transport for NATS before anything subscribes.
    """

    def __init__(self, inner: Bus | None = None):
        self.inner: Bus = inner or InProcessBus()

    async def publish(self, subject: str, data: bytes, headers: dict[str, str] | None = None) -> None:
        await self.inner.publish(subject, data, headers)

    async def subscribe(self, subject: str, handler: Handler) -> Subscription:
        return await self.inner.subscribe(subject, handler)

    async def request(
        self, subject: str, data: bytes, timeout: float, headers: dict[str, str] | None = None
    ) -> Msg:
        return await self.inner.request(subject, data, timeout, headers)

    async def serve(self, subject: str, responder: Responder) -> Subscription:
        return await self.inner.serve(subject, responder)

    async def close(self) -> None:
        await self.inner.close()
