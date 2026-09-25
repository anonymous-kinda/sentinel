"""NatsBus and the node's own nats-server: waiting for it, then keeping it.

A node connects to the nats-server beside it, which may still be starting.
The node waits for it a bounded time, saying so (sentinel/api/app.py), and
fails clearly after that. Once connected, the client reconnects for ever.
"""

from __future__ import annotations

import asyncio

import nats
import nats.aio.transport
import pytest

from sentinel.bus.nats_bus import NatsBus


def test_the_first_connect_gives_up_so_the_node_can_say_it_is_waiting(monkeypatch):
    """Unlimited reconnects applied to the first connect too, so the client
    retried inside it for ever: the node's own 60-attempt loop never ran,
    'Waiting for nats-server' was never logged, /api/health never answered."""

    async def refused(*args, **kwargs):
        raise ConnectionRefusedError("nothing listens")

    monkeypatch.setattr(nats.aio.transport.asyncio, "open_connection", refused)

    async def first_connect():
        return await asyncio.wait_for(NatsBus.connect("nats://127.0.0.1:4222", "sentinel-test"), 3.0)

    with pytest.raises(ConnectionError):     # a refusal, not the TimeoutError of waiting for ever
        asyncio.run(first_connect())


def test_once_connected_it_reconnects_for_ever(monkeypatch):
    class Client:
        def __init__(self, options: dict):
            self.options = options

    async def connected(**options):
        return Client(options)

    monkeypatch.setattr(nats, "connect", connected)
    bus = asyncio.run(NatsBus.connect("nats://127.0.0.1:4222", "sentinel-test"))
    assert bus._nc.options["allow_reconnect"] is True
    assert bus._nc.options["max_reconnect_attempts"] == -1
    assert bus._nc.options["reconnect_time_wait"] > 0
