"""GET /api/stream: this node's bus events as server-sent events.

A subscriber that cannot keep up is never dropped from silently. When its
queue fills, the node logs "Stream subscriber overflowed" and closes that
subscriber's stream. The console reconnects after a closed stream and
re-reads everything when one opens (web/src/api/client.ts: useStream and
STREAM_OPENED), so an operator never misses an update without the console
knowing.

Driven at the ASGI level: TestClient cannot stop reading a stream halfway,
which is the one thing a slow client does.
"""

import asyncio
import contextlib
import datetime as dt
import json

from sentinel.api import create_app
from sentinel.api.app import STREAM_QUEUE_SLOTS
from sentinel.api.settings import Settings
from sentinel.bus import subjects
from sentinel.clock import FixedClock

NOW = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
NODE_ID = "edge"
KIND = "ops.changed"
SCOPE = {
    "type": "http",
    "asgi": {"version": "3.0", "spec_version": "2.4"},
    "http_version": "1.1",
    "method": "GET",
    "scheme": "http",
    "path": "/api/stream",
    "raw_path": b"/api/stream",
    "root_path": "",
    "query_string": b"",
    "headers": [],
    "client": ("127.0.0.1", 50000),
    "server": ("testserver", 80),
}


class SseClient:
    """Reads the stream as a browser would, but can stop reading. It never
    hangs up: whatever ends a stream here, the node ended it."""

    def __init__(self):
        self.chunks: list[bytes] = []
        self.ended = False
        self.reading = asyncio.Event()
        self.reading.set()
        self.opened = asyncio.Event()

    async def send(self, message):
        if message["type"] != "http.response.body":
            return
        self.chunks.append(message["body"])
        self.ended = not message.get("more_body", False)
        self.opened.set()
        await self.reading.wait()

    async def receive(self):
        await asyncio.Event().wait()

    def events(self) -> list[dict]:
        blocks = b"".join(self.chunks).decode().split("\n\n")
        return [json.loads(b.split("data: ", 1)[1]) for b in blocks if b.startswith(f"event: {KIND}\n")]


def open_app(tmp_path):
    settings = Settings(
        node_id=NODE_ID, exercise=False, library=False, web_dist=None, var_dir=str(tmp_path), ai=False
    )
    return create_app(settings, clock=FixedClock(NOW), start_background=False)


async def publish(node, n: int) -> None:
    await node.bus.publish(subjects.local(NODE_ID, KIND), json.dumps({"n": n}).encode(), {"Sentinel-Kind": KIND})


async def until(condition, timeout_s: float = 5.0) -> None:
    async with asyncio.timeout(timeout_s):
        while not condition():
            await asyncio.sleep(0.001)


def overflows(caplog) -> list[dict]:
    return [r.fields for r in caplog.records if r.getMessage() == "Stream subscriber overflowed"]


def test_a_subscriber_that_falls_behind_is_logged_and_its_stream_closed(tmp_path, caplog):
    app = open_app(tmp_path)
    published = 2 * STREAM_QUEUE_SLOTS

    async def scenario() -> SseClient:
        client = SseClient()
        client.reading.clear()  # takes the first chunk, then stops reading
        stream = asyncio.create_task(app(SCOPE, client.receive, client.send))
        await asyncio.wait_for(client.opened.wait(), 5)
        for n in range(published):
            await publish(app.state.node, n)
        client.reading.set()
        await asyncio.wait_for(stream, 5)  # the node ended it
        return client

    client = asyncio.run(scenario())
    assert client.ended, "the stream is closed, so the console reconnects and re-reads"
    assert len(client.events()) < published
    [fields] = overflows(caplog)
    assert fields["slots"] == STREAM_QUEUE_SLOTS and fields["kind"] == KIND


def test_the_interface_says_how_far_behind_a_subscriber_may_fall(tmp_path):
    description = open_app(tmp_path).openapi()["paths"]["/api/stream"]["get"]["description"]
    assert f"falls {STREAM_QUEUE_SLOTS} events behind" in description


def test_a_subscriber_that_keeps_up_gets_every_event_and_stays_open(tmp_path, caplog):
    """The control: the same volume, read as it arrives, closes nothing."""
    app = open_app(tmp_path)
    published = 2 * STREAM_QUEUE_SLOTS
    batch = STREAM_QUEUE_SLOTS // 2

    async def scenario() -> SseClient:
        client = SseClient()
        stream = asyncio.create_task(app(SCOPE, client.receive, client.send))
        await asyncio.wait_for(client.opened.wait(), 5)
        for end in range(batch, published + 1, batch):
            for n in range(end - batch, end):
                await publish(app.state.node, n)
            await until(lambda sent=end: len(client.events()) == sent)
        await asyncio.sleep(0.05)
        assert not stream.done() and not client.ended, "the stream is still open"
        stream.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stream
        return client

    client = asyncio.run(scenario())
    assert [e["n"] for e in client.events()] == list(range(published))
    assert overflows(caplog) == []
