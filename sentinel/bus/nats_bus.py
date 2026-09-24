"""NATS implementation of the Bus (ADR-004).

Each node connects to its *own* nats-server on localhost. The server, not
the client, holds the link to other nodes (a leafnode connection), so a
degraded or denied link never breaks the node's local bus: the console,
the store and the engine keep working and the leaf reconnects on its own.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import nats
from nats.errors import NoRespondersError
from nats.errors import TimeoutError as NatsTimeout

from ..obs import get_logger
from .base import Handler, Msg, NoResponders, RequestTimeout, Responder

if TYPE_CHECKING:
    from nats.aio.client import Client
    from nats.aio.msg import Msg as NatsMsg
    from nats.aio.subscription import Subscription as NatsSubscription

log = get_logger(__name__)


class _Sub:
    def __init__(self, sub: NatsSubscription):
        self._sub = sub

    async def unsubscribe(self) -> None:
        with contextlib.suppress(Exception):  # already closed
            await self._sub.unsubscribe()


class NatsBus:
    def __init__(self, nc: Client):
        self._nc = nc

    @classmethod
    async def connect(cls, url: str, name: str) -> NatsBus:
        nc = await nats.connect(
            servers=[url],
            name=name,
            allow_reconnect=True,
            max_reconnect_attempts=-1,
            reconnect_time_wait=1,
            ping_interval=10,
            max_outstanding_pings=5,
        )
        log.info("Connected to NATS", url=url, client_name=name)
        return cls(nc)

    @property
    def connected(self) -> bool:
        return self._nc.is_connected

    async def publish(self, subject: str, data: bytes, headers: dict[str, str] | None = None) -> None:
        await self._nc.publish(subject, data, headers=headers or None)

    async def subscribe(self, subject: str, handler: Handler) -> _Sub:
        async def cb(m: NatsMsg) -> None:
            await handler(Msg(m.subject, m.data, dict(m.headers or {})))

        return _Sub(await self._nc.subscribe(subject, cb=cb))

    async def request(
        self, subject: str, data: bytes, timeout: float, headers: dict[str, str] | None = None
    ) -> Msg:
        try:
            m = await self._nc.request(subject, data, timeout=timeout, headers=headers or None)
        except NoRespondersError as exc:
            raise NoResponders(subject) from exc
        except NatsTimeout as exc:
            raise RequestTimeout(subject) from exc
        return Msg(m.subject, m.data, dict(m.headers or {}))

    async def serve(self, subject: str, responder: Responder) -> _Sub:
        async def cb(m: NatsMsg) -> None:
            try:
                body, headers = await responder(Msg(m.subject, m.data, dict(m.headers or {})))
            except Exception:  # noqa: BLE001 - never kill the subscription
                log.exception("Responder failed", subject=subject)
                body, headers = b"", {"Sentinel-Error": "responder-failed"}
            if m.reply:
                await self._nc.publish(m.reply, body, headers=headers or None)

        return _Sub(await self._nc.subscribe(subject, queue="sentinel", cb=cb))

    async def close(self) -> None:
        try:
            await self._nc.drain()
        except Exception:  # noqa: BLE001
            await self._nc.close()
