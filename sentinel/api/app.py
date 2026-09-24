"""The node process: API, exercise feeder, NASA reference library, SSE.

One application serves three deployment roles. ADR-009: each node serves
its own UI, so an operator's console never depends on the link to another
node - the thing that goes away first in a denied environment.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import pathlib
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..bus import Bus, InProcessBus, Msg
from ..clock import Clock, from_env
from ..conjunction.exercise import generate
from ..conjunction.service import ConjunctionService
from ..conjunction.store import ConjunctionStore
from .settings import Settings
from .validation_view import ValidationView

log = logging.getLogger("sentinel.node")

STREAM_SUBJECTS = ("cdm.>", "ops.>", "sync.>", "link.>", "passes.>", "ai.>")

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'wasm-unsafe-eval'",  # Cesium decoders are WebAssembly; JS eval stays blocked
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "worker-src 'self' blob:",
        "connect-src 'self'",
        "font-src 'self' data:",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ]
)


@dataclasses.dataclass
class Node:
    settings: Settings
    clock: Clock
    bus: Bus
    store: ConjunctionStore
    conjunctions: ConjunctionService
    validation: ValidationView
    tasks: list[asyncio.Task] = dataclasses.field(default_factory=list)
    extensions: dict = dataclasses.field(default_factory=dict)


async def _load_library(node: Node) -> int:
    """NASA CARA's published operational conjunctions, as REAL reference events."""
    from ..validation.cara import CARA_DIR

    directory = CARA_DIR / "PcTestCaseCDMs"
    if not directory.exists():
        log.warning("NASA CARA library not present at %s; skipping", directory)
        return 0
    count = 0
    for path in sorted(directory.glob("*.cdm")):
        result = await node.conjunctions.ingest(path.read_bytes(), "nasa-cara-library", "REAL")
        count += result.status == "accepted"
    return count


async def _exercise_feeder(node: Node) -> None:
    """Release the scripted exercise CDMs as the clock reaches them."""
    schedule = generate(node.clock.now())
    for item in schedule:
        while node.clock.now() < item.release_at:
            await asyncio.sleep(0.5)
        await node.conjunctions.ingest(item.kvn.encode(), "exercise-feed", "EXERCISE")


def build_node(settings: Settings, clock: Clock | None = None, bus: Bus | None = None) -> Node:
    clock = clock or from_env()
    bus = bus or InProcessBus()
    store = ConjunctionStore(settings.db_path)
    service = ConjunctionService(store, bus, clock)
    return Node(settings, clock, bus, store, service, ValidationView())


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    bus: Bus | None = None,
    start_background: bool = True,
) -> FastAPI:
    settings = settings or Settings.from_env()
    node = build_node(settings, clock, bus)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.library:
            loaded = await _load_library(node)
            log.info("loaded %d NASA CARA reference events", loaded)
        if settings.exercise and start_background:
            node.tasks.append(asyncio.create_task(_exercise_feeder(node)))
        for hook in node.extensions.get("startup", []):
            await hook(node)
        yield
        for task in node.tasks:
            task.cancel()
        for hook in node.extensions.get("shutdown", []):
            await hook(node)
        await node.bus.close()

    app = FastAPI(title="Sentinel", version=__version__, lifespan=lifespan)
    app.state.node = node

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        # default-src 'self' makes "the console never calls out" a property the
        # browser enforces, not a promise: a request to any other origin -
        # tile server, CDN, font host, telemetry - is blocked. Cesium needs
        # blob: workers and data: images; nothing else is allowed.
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        return response

    # ----------------------------------------------------------------- node
    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "node_id": settings.node_id, "version": __version__}

    @app.get("/api/node")
    def node_info() -> dict:
        return {
            "node_id": settings.node_id,
            "role": settings.role,
            "version": __version__,
            "engine_version": node.conjunctions.engine_version,
            "marking": settings.marking,
            "clock": node.clock.label,
            "now": node.clock.now().isoformat(),
            "read_only": settings.read_only,
            "demo_controls": settings.demo_controls,
            "modules": ["conjunction", *node.extensions.get("modules", [])],
            "policy": dataclasses.asdict(node.conjunctions.policy),
        }

    # --------------------------------------------------------- conjunctions
    @app.get("/api/events")
    def events(scope: str = "active") -> list[dict]:
        if scope not in {"active", "past", "all"}:
            raise HTTPException(400, "scope must be active, past or all")
        return node.conjunctions.list_events(scope)

    @app.get("/api/events/{event_id}")
    def event(event_id: str) -> dict:
        detail = node.conjunctions.event_detail(event_id)
        if detail is None:
            raise HTTPException(404, "no such event")
        return detail

    @app.get("/api/events/{event_id}/encounter")
    def encounter(event_id: str) -> dict:
        data = node.conjunctions.encounter(event_id)
        return data if data is not None else {"available": False, "reason": "no covariance or HBR"}

    @app.get("/api/events/{event_id}/dilution-curve")
    def dilution_curve(event_id: str) -> dict:
        data = node.conjunctions.dilution_curve(event_id)
        return data if data is not None else {"available": False}

    @app.get("/api/events/{event_id}/trajectory")
    def trajectory(event_id: str) -> dict:
        data = node.conjunctions.trajectory(event_id)
        if data is None:
            raise HTTPException(404, "no such event")
        return data

    @app.post("/api/ingest/cdm")
    async def ingest(request: Request, response: Response) -> dict:
        if settings.read_only:
            raise HTTPException(403, "this node is read-only")
        raw = await request.body()
        if len(raw) > 1_000_000:
            raise HTTPException(413, "a CDM is a few kilobytes; refusing a megabyte")
        result = await node.conjunctions.ingest(raw, "api-upload", "REAL")
        response.status_code = {"accepted": 201, "duplicate": 200, "rejected": 422}[result.status]
        return dataclasses.asdict(result)

    @app.get("/api/quarantine")
    def quarantine() -> list[dict]:
        return node.conjunctions.quarantined()

    @app.get("/api/validation")
    def validation() -> dict:
        return node.validation.summary()

    # ------------------------------------------------------------------ SSE
    @app.get("/api/stream")
    async def stream(request: Request) -> StreamingResponse:
        queue: asyncio.Queue[Msg] = asyncio.Queue(maxsize=256)

        async def enqueue(msg: Msg) -> None:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(msg)

        subs = [await node.bus.subscribe(s, enqueue) for s in STREAM_SUBJECTS]

        async def events_out() -> AsyncIterator[str]:
            try:
                yield "retry: 3000\n\n"
                while not await request.is_disconnected():
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    kind = msg.headers.get("Sentinel-Kind", msg.subject)
                    body = msg.data.decode("utf-8", "replace")
                    try:
                        json.loads(body)
                    except ValueError:
                        body = json.dumps({"subject": msg.subject})
                    yield f"event: {kind}\ndata: {body}\n\n"
            finally:
                for sub in subs:
                    await sub.unsubscribe()

        return StreamingResponse(events_out(), media_type="text/event-stream")

    # ------------------------------------------------------------ extensions
    for register in _extension_registrars():
        register(app, node)

    # --------------------------------------------------------------- web UI
    if settings.web_dist and pathlib.Path(settings.web_dist).exists():
        app.mount("/", StaticFiles(directory=settings.web_dist, html=True), name="web")

    return app


def _extension_registrars():
    """Routers contributed by later modules (sync, passes, AI)."""
    from . import extensions

    return extensions.REGISTRARS
