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
import pathlib
from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..bus import Bus, LateBus, Msg, subjects
from ..clock import Clock, from_env
from ..conjunction.exercise import generate
from ..conjunction.service import ConjunctionService
from ..conjunction.store import ConjunctionStore
from ..conjunction.sync_adapter import ConjunctionRecords
from ..linkstate import LinkMonitor
from ..obs import get_logger
from ..ops import DECISIONS, OpsService, load_identity
from ..passes.catalog import DEFAULT_CATALOG, load_catalog
from ..passes.element_store import ElementStore, default_snapshot
from ..passes.sync_adapter import PREFIX as ELEMENT_PREFIX
from ..passes.sync_adapter import ElementRecords
from ..sync import SyncAgent, SyncServer
from .identity import operator_of
from .records import CompositeRecords
from .settings import Settings
from .validation_view import ValidationView

log = get_logger("sentinel.node")


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
    bus: LateBus
    store: ConjunctionStore
    conjunctions: ConjunctionService
    validation: ValidationView
    ops: OpsService
    link: LinkMonitor
    elements: ElementStore = dataclasses.field(default_factory=ElementStore)
    offered_elements: Callable[[int], bool] | None = None
    sync_agent: SyncAgent | None = None
    sync_server: SyncServer | None = None
    toxiproxy: object | None = None
    tasks: list[asyncio.Task] = dataclasses.field(default_factory=list)
    extensions: dict = dataclasses.field(default_factory=dict)


async def _load_library(node: Node) -> int:
    """NASA CARA's published operational conjunctions, as REAL reference events."""
    from ..validation.cara import CARA_DIR

    directory = CARA_DIR / "PcTestCaseCDMs"
    if not directory.exists():
        log.warning("Reference library missing", path=str(directory))
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


def _element_snapshot(settings: Settings) -> pathlib.Path | None:
    """Which OMM snapshot this node starts from. A hub or standalone node
    loads the vendored public snapshot unless told otherwise; an edge loads
    one only if configured, and otherwise receives element sets from its
    hub through sync."""
    if settings.elements_path:
        return pathlib.Path(settings.elements_path)
    return None if settings.role == "edge" else default_snapshot()


def _load_elements(settings: Settings) -> ElementStore:
    store = ElementStore()
    path = _element_snapshot(settings)
    if path is None:
        return store
    if not path.exists():
        log.warning("Element snapshot missing", path=str(path), role=settings.role)
        return store
    loaded = store.load_snapshot(path, source=path.name)
    log.info("Element sets loaded", path=str(path), accepted=loaded.accepted, rejected=loaded.rejected)
    return store


SYNC_ELEMENT_SCOPES = ("catalog", "all")


def _offered_elements(settings: Settings) -> Callable[[int], bool] | None:
    """Which element sets this node offers over sync: by default only the
    imaging catalog the pass module uses; `all` for every set it holds."""
    if settings.sync_elements not in SYNC_ELEMENT_SCOPES:
        raise ValueError(f"SENTINEL_SYNC_ELEMENTS must be one of {SYNC_ELEMENT_SCOPES}")
    if settings.sync_elements == "all":
        return None
    catalog_ids = frozenset(imager.norad_id for imager in load_catalog(DEFAULT_CATALOG))
    return catalog_ids.__contains__


def _sync_records(node: Node) -> CompositeRecords:
    """Every mission module's reference data behind one sync interface:
    conjunction CDMs by default, element sets by their `omm:` prefix."""

    async def elements_changed() -> None:
        for hook in node.extensions.get("elements_changed", []):
            await hook(node)

    elements = ElementRecords(
        node.elements, node.clock, on_accepted=elements_changed, offered=node.offered_elements
    )
    return CompositeRecords(ConjunctionRecords(node.conjunctions), {ELEMENT_PREFIX: elements})


def build_node(settings: Settings, clock: Clock | None = None, bus: Bus | None = None) -> Node:
    clock = clock or from_env()
    late = LateBus(bus) if bus is not None else LateBus()
    store = ConjunctionStore(settings.db_path)
    conjunctions = ConjunctionService(store, late, clock, node_id=settings.node_id)
    var = pathlib.Path(settings.var_dir)
    var.mkdir(parents=True, exist_ok=True)
    key, trust = load_identity(
        settings.node_id, var, pathlib.Path(settings.trust_file) if settings.trust_file else None
    )
    ops = OpsService(
        settings.node_id, key, trust, late, clock,
        db_path=settings.db_path, current_ref=conjunctions.current_ref,
    )
    node = Node(
        settings, clock, late, store, conjunctions, ValidationView(), ops, LinkMonitor(),
        elements=_load_elements(settings),
        offered_elements=_offered_elements(settings),
    )
    if settings.toxiproxy_api or settings.demo_controls:
        from ..linkstate.toxiproxy import ToxiproxyControl

        node.toxiproxy = ToxiproxyControl(settings.toxiproxy_api)
    return node


async def _connect_nats(node: Node) -> None:
    """Swap the in-process transport for this node's own nats-server."""
    from ..bus.nats_bus import NatsBus

    for attempt in range(60):
        try:
            node.bus.inner = await NatsBus.connect(node.settings.nats_url, f"sentinel-{node.settings.node_id}")
            return
        except Exception as exc:  # noqa: BLE001 - nats-server may still be starting
            if attempt == 59:
                raise
            log.info("Waiting for nats-server", attempt=attempt, error=type(exc).__name__)
            await asyncio.sleep(0.5)


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
        if settings.nats_url:
            await _connect_nats(node)
        records = _sync_records(node)
        if settings.role == "hub":
            node.sync_server = SyncServer(node.bus, records, node.ops, settings.node_id)
            await node.sync_server.start()
        if settings.role == "edge" and settings.hub_id:
            node.sync_agent = SyncAgent(
                node.bus, records, node.ops, node.clock, settings.node_id, settings.hub_id,
                node.link, mode=settings.sync_mode, interval_s=settings.sync_interval_s,
                urgent_window_s=node.conjunctions.policy.urgent_window_s,
            )
            if start_background:
                node.tasks.append(asyncio.create_task(node.sync_agent.run()))
        if settings.library:
            loaded = await _load_library(node)
            log.info("Reference library loaded", events=loaded)
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
            "modules": ["conjunction", "ops", *(["sync"] if settings.role != "standalone" else []),
                        *node.extensions.get("modules", [])],
            "hub_id": settings.hub_id,
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

    # ------------------------------------------------------- operator data
    def operator(request: Request) -> str:
        return operator_of(request, settings.node_id)

    def writable() -> None:
        if settings.read_only:
            raise HTTPException(403, "this node is read-only")

    @app.get("/api/events/{event_id}/ops")
    def event_ops(event_id: str) -> dict:
        return {
            "entries": node.ops.entries(event_id),
            "annotations": node.ops.annotations(event_id),
            "current_ref": node.conjunctions.current_ref(event_id),
            "decisions": list(DECISIONS),
        }

    @app.post("/api/events/{event_id}/decision")
    async def decision(event_id: str, request: Request) -> dict:
        writable()
        body = await request.json()
        if body.get("decision") not in DECISIONS:
            raise HTTPException(422, f"decision must be one of {DECISIONS}")
        return await node.ops.append(
            event_id,
            "DECISION",
            {"decision": body["decision"], "rationale": str(body.get("rationale", ""))[:2000]},
            operator(request),
        )

    @app.post("/api/events/{event_id}/note")
    async def note(event_id: str, request: Request) -> dict:
        writable()
        body = await request.json()
        return await node.ops.append(event_id, "NOTE", {"text": str(body.get("text", ""))[:2000]}, operator(request))

    @app.post("/api/events/{event_id}/annotation")
    async def annotation(event_id: str, request: Request) -> dict:
        writable()
        body = await request.json()
        try:
            return await node.ops.annotate(event_id, body.get("field"), body.get("value"), operator(request))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/ops/digest")
    def ops_digest() -> dict:
        return {**node.ops.digest(), "conflicts": node.ops.conflicts(), "rejected": node.ops.log.rejected}

    # ------------------------------------------------------ link and sync
    @app.get("/api/link")
    def link() -> dict:
        out = {"role": settings.role, "hub_id": settings.hub_id, "monitor": node.link.snapshot()}
        if node.toxiproxy is not None and settings.demo_controls:
            try:
                out["emulation"] = node.toxiproxy.status()
            except Exception as exc:  # noqa: BLE001 - report, don't fail the endpoint
                log.warning("Link emulator unreachable", error=type(exc).__name__)
                out["emulation"] = None
        return out

    @app.post("/api/demo/link")
    async def demo_link(request: Request) -> dict:
        client = request.client.host if request.client else ""
        if not settings.demo_controls or client not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise HTTPException(403, "link emulation controls are disabled on this node")
        if node.toxiproxy is None:
            raise HTTPException(503, "no link emulator configured")
        body = await request.json()
        try:
            status = node.toxiproxy.apply(str(body.get("preset")))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        await node.bus.publish(
            subjects.local(settings.node_id, "link.emulation"),
            json.dumps(status).encode(),
            {"Sentinel-Kind": "link.emulation"},
        )
        return status

    @app.get("/api/sync")
    def sync_status() -> dict:
        if node.sync_agent is not None:
            return {"role": "edge", **node.sync_agent.status()}
        if node.sync_server is not None:
            return {"role": "hub", "requests": node.sync_server.requests}
        return {"role": settings.role}

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

        subs = [await node.bus.subscribe(subjects.local_all(settings.node_id), enqueue)]

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
