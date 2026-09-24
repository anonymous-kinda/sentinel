"""OPSEC evidence for the harness: find a unit's position in bytes, and
capture everything a nats-server carries.

`leak_patterns` lists every form a unit could travel or rest in: its id,
its coordinates as text at the precisions worth leaking, as IEEE-754 bytes
(the form CBOR and any binary codec use), and its Earth-fixed position.
`Capture` subscribes to `>` on one nats-server from a background thread,
so a scenario can drive real processes while it listens.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import pathlib
import struct
import threading

import nats

from sentinel.passes.model import Unit
from sentinel.passes.topocentric import Site

COORDINATES = ("lat_deg", "lon_deg")
TEXT_DECIMALS = (4, 5, 6)     # 4 decimals is ~11 m: coarser is not a position worth hiding


def leak_patterns(unit: dict) -> dict[str, bytes]:
    patterns = {"unit_id": unit["unit_id"].encode()}
    for field in COORDINATES:
        value = float(unit[field])
        patterns[f"{field} text"] = repr(value).encode()
        for decimals in TEXT_DECIMALS:
            patterns[f"{field} text {decimals} dp"] = f"{value:.{decimals}f}".encode()
        patterns[f"{field} float64 big-endian"] = struct.pack(">d", value)
        patterns[f"{field} float64 little-endian"] = struct.pack("<d", value)
        patterns[f"{field} float32 big-endian"] = struct.pack(">f", value)
        patterns[f"{field} float32 little-endian"] = struct.pack("<f", value)
    ecef_km = Site.from_unit(Unit(**unit)).ecef_km
    for axis, value_km in zip("xyz", ecef_km):
        patterns[f"ecef {axis} km"] = f"{value_km:.3f}".encode()
        patterns[f"ecef {axis} m"] = f"{value_km * 1000.0:.1f}".encode()
    return patterns


def find_leaks(blob: bytes, patterns: dict[str, bytes]) -> list[str]:
    return [name for name, pattern in patterns.items() if pattern in blob]


def scan_tree(root: pathlib.Path, patterns: dict[str, bytes]) -> dict[str, list[str]]:
    """Every file under root that holds any pattern, by relative path."""
    found = {}
    for path in sorted(p for p in pathlib.Path(root).rglob("*") if p.is_file()):
        leaks = find_leaks(path.read_bytes(), patterns)
        if leaks:
            found[path.relative_to(root).as_posix()] = leaks
    return found


@dataclasses.dataclass(frozen=True)
class Captured:
    subject: str
    data: bytes
    headers: dict[str, str]

    def blob(self) -> bytes:
        return self.subject.encode() + b"\n" + json.dumps(self.headers).encode() + b"\n" + self.data


class Capture:
    """Every message a nats-server delivers on `subject`, recorded in order.

    Subscribing to `>` on the hub's server is also the adversarial case: the
    interest propagates to the edge over the leaf, so the edge forwards
    everything its leaf permissions allow."""

    def __init__(self, url: str, subject: str = ">"):
        self.url = url
        self.subject = subject
        self.messages: list[Captured] = []
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._error: BaseException | None = None

    def __enter__(self) -> Capture:
        self._thread = threading.Thread(target=self._run, name=f"capture {self.url}", daemon=True)
        self._thread.start()
        if not self._ready.wait(15) or self._error is not None:
            raise RuntimeError(f"capture on {self.url} did not start: {self._error!r}")
        return self

    def __exit__(self, *exc) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(15)

    def _run(self) -> None:
        try:
            asyncio.run(self._listen())
        except BaseException as exc:  # noqa: BLE001 - reported to the scenario through __enter__
            self._error = exc
            self._ready.set()

    async def _listen(self) -> None:
        client = await nats.connect(self.url, name="opsec-capture", allow_reconnect=False)

        async def record(msg) -> None:
            self.messages.append(Captured(msg.subject, msg.data, dict(msg.headers or {})))

        await client.subscribe(self.subject, cb=record)
        await client.flush()
        self._loop, self._stop = asyncio.get_running_loop(), asyncio.Event()
        self._ready.set()
        await self._stop.wait()
        await client.drain()


def publish(url: str, messages: list[tuple[str, bytes]]) -> None:
    """Publish from a fresh client, as any process on that server could."""

    async def send() -> None:
        client = await nats.connect(url, name="opsec-canary", allow_reconnect=False)
        for subject, data in messages:
            await client.publish(subject, data)
        await client.flush()
        await client.close()

    asyncio.run(send())
