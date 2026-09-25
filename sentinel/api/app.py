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

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..bus import Bus, LateBus, Msg, subjects
from ..clock import Clock, from_env
from ..conjunction.exercise import generate
from ..conjunction.service import ConjunctionService
from ..conjunction.store import ConjunctionStore
from ..conjunction.sync_adapter import ConjunctionRecords
from ..conjunction.trajectory import TrajectoryUnavailable
from ..linkstate import LinkMonitor
from ..linkstate.toxiproxy import PRESETS as TOXIPROXY_PRESETS
from ..obs import get_logger
from ..ops import DECISIONS, OpsService, load_identity
from ..ops.service import ANNOTATION_FIELDS, TRIAGE_STATUSES
from ..passes.catalog import DEFAULT_CATALOG, load_catalog
from ..passes.element_store import ElementStore, default_snapshot
from ..passes.sync_adapter import PREFIX as ELEMENT_PREFIX
from ..passes.sync_adapter import ElementRecords
from ..sync import SyncAgent, SyncServer
from . import apidoc
from .bodies import BodyLimit, json_object, refuse_writes_on_read_only
from .identity import operator_of
from .records import CompositeRecords
from .settings import Settings
from .validation_view import ValidationView

log = get_logger("sentinel.node")

# Events a stream subscriber may fall behind by before its stream is closed.
STREAM_QUEUE_SLOTS = 256

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


def _runs_sync(node: Node) -> bool:
    """Whether this node serves or pulls sync: what it built, not what its role implies."""
    return node.sync_server is not None or node.sync_agent is not None


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

    app = FastAPI(
        title="Sentinel",
        version=__version__,
        description=apidoc.DESCRIPTION,
        openapi_tags=apidoc.TAGS,
        lifespan=lifespan,
        dependencies=[Depends(refuse_writes_on_read_only)],
    )
    app.state.node = node
    app.add_middleware(BodyLimit)

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
    @app.get("/api/health", tags=[apidoc.NODE], summary="Liveness")
    def health() -> dict:
        """200 while the process serves HTTP, with this node's id and version."""
        return {"status": "ok", "node_id": settings.node_id, "version": __version__}

    @app.get("/api/node", tags=[apidoc.NODE], summary="This node: role, marking, clock, modules, policy")
    def node_info() -> dict:
        """Identity and configuration the console needs before anything else.
        `modules` lists what this node runs (`conjunction`, `ops`, `sync`, `ai`, ...);
        `policy` is the operator's banding and maneuver-commit-point assumptions."""
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
            "modules": ["conjunction", "ops", *(["sync"] if _runs_sync(node) else []),
                        *node.extensions.get("modules", [])],
            "hub_id": settings.hub_id,
            "policy": dataclasses.asdict(node.conjunctions.policy),
        }

    # --------------------------------------------------------- conjunctions
    @app.get("/api/events", tags=[apidoc.CONJUNCTIONS], summary="List conjunction events")
    def events(scope: str = "active") -> list[dict]:
        """`scope`: `active` (TCA in the future, soonest maneuver commit point first),
        `past` or `all` (newest TCA first); 400 otherwise. An edge also lists events it
        knows only from the hub's summaries, marked `verification: HUB_ASSERTED` until
        their CDMs arrive and are re-assessed locally."""
        if scope not in {"active", "past", "all"}:
            raise HTTPException(400, "scope must be active, past or all")
        return node.conjunctions.list_events(scope)

    @app.get("/api/events/{event_id}", tags=[apidoc.CONJUNCTIONS], summary="One event: summary and CDM history")
    def event(event_id: str) -> dict:
        """The event summary, every CDM received for it with its own assessment and
        admission warnings, and the engine version and policy that produced them. 404 when
        the event is unknown."""
        detail = node.conjunctions.event_detail(event_id)
        if detail is None:
            raise HTTPException(404, "no such event")
        return detail

    @app.get("/api/events/{event_id}/encounter", tags=[apidoc.CONJUNCTIONS], summary="Encounter-plane geometry")
    def encounter(event_id: str) -> dict:
        """Miss vector, projected covariance ellipse and hard-body radius in the encounter
        plane, for display. `available: false` with a reason when there is no covariance or
        no hard-body radius."""
        data = node.conjunctions.encounter(event_id)
        return data if data is not None else {"available": False, "reason": "no covariance or HBR"}

    @app.get("/api/events/{event_id}/dilution-curve", tags=[apidoc.CONJUNCTIONS], summary="Pc against covariance scale")
    def dilution_curve(event_id: str) -> dict:
        """Pc as the covariance is scaled by k (log10 grid), with the maximizing scale k*.
        `diluted` is true when k* < 1: the Pc would rise if the data were better.
        `available: false` when the curve cannot be computed."""
        data = node.conjunctions.dilution_curve(event_id)
        return data if data is not None else {"available": False}

    @app.get("/api/events/{event_id}/trajectory", tags=[apidoc.CONJUNCTIONS], summary="Two-body arcs around TCA")
    def trajectory(event_id: str) -> dict:
        """Earth-fixed arcs of both objects around TCA. Visualization only; 404 when the
        event is unknown, 422 when two-body arcs cannot be drawn for its states (a state
        below the Earth's surface or beyond the admitted 3 million km, a propagation that fails, or
        an arc past the last representable date)."""
        try:
            data = node.conjunctions.trajectory(event_id)
        except TrajectoryUnavailable as exc:
            raise HTTPException(422, "the two-body arcs cannot be drawn for this event") from exc
        if data is None:
            raise HTTPException(404, "no such event")
        return data

    @app.post(
        "/api/ingest/cdm",
        tags=[apidoc.CONJUNCTIONS],
        summary="Admit one CDM (CCSDS 508.0-B-1 KVN)",
        openapi_extra=apidoc.KVN_BODY,
        responses=apidoc.INGEST_RESPONSES,
    )
    async def ingest(request: Request, response: Response) -> dict:
        """The admission policy of docs/icd/cdm-profile.md: wrong input is quarantined with
        a code, incomplete input is accepted with warnings. Admitted as REAL data unless its
        ORIGINATOR marks it EXERCISE or DERIVED."""
        raw = await request.body()
        result = await node.conjunctions.ingest(raw, "api-upload", "REAL")
        response.status_code = {"accepted": 201, "duplicate": 200, "rejected": 422}[result.status]
        return dataclasses.asdict(result)

    # ------------------------------------------------------- operator data
    def operator(request: Request) -> str:
        return operator_of(request, settings.node_id)

    @app.get("/api/events/{event_id}/ops", tags=[apidoc.OPERATOR_DATA], summary="Decision log and annotations for an event")
    def event_ops(event_id: str) -> dict:
        """Signed log entries (each with `signature_valid`, and `review_required` when its
        CDM has been superseded), annotations with concurrent values kept as a conflict, the
        CDM a new decision would be made against, and the allowed decisions."""
        return {
            "entries": node.ops.entries(event_id),
            "annotations": node.ops.annotations(event_id),
            "current_ref": node.conjunctions.current_ref(event_id),
            "decisions": list(DECISIONS),
        }

    @app.post(
        "/api/events/{event_id}/decision",
        tags=[apidoc.OPERATOR_DATA],
        summary="Record a decision",
        openapi_extra=apidoc.json_body(
            {"decision": {"enum": list(DECISIONS)}, "rationale": apidoc.text("truncated to 2000 characters")},
            required=("decision",),
        ),
    )
    async def decision(event_id: str, request: Request) -> dict:
        """Appends a signed DECISION to the log, bound to the event's current CDM. 422 on a
        decision outside the list; 403 on a read-only node."""
        body = await json_object(request)
        if body.get("decision") not in DECISIONS:
            raise HTTPException(422, f"decision must be one of {DECISIONS}")
        return await node.ops.append(
            event_id,
            "DECISION",
            {"decision": body["decision"], "rationale": str(body.get("rationale", ""))[:2000]},
            operator(request),
        )

    @app.post(
        "/api/events/{event_id}/note",
        tags=[apidoc.OPERATOR_DATA],
        summary="Add a note",
        openapi_extra=apidoc.json_body({"text": apidoc.text("truncated to 2000 characters")}),
    )
    async def note(event_id: str, request: Request) -> dict:
        """Appends a signed NOTE to the log. 403 on a read-only node."""
        body = await json_object(request)
        return await node.ops.append(event_id, "NOTE", {"text": str(body.get("text", ""))[:2000]}, operator(request))

    @app.post(
        "/api/events/{event_id}/annotation",
        tags=[apidoc.OPERATOR_DATA],
        summary="Set an annotation",
        openapi_extra=apidoc.json_body(
            {
                "field": {"enum": list(ANNOTATION_FIELDS)},
                "value": {"description": "for triage_status, one of " + ", ".join(TRIAGE_STATUSES)},
            },
            required=("field", "value"),
        ),
    )
    async def annotation(event_id: str, request: Request) -> dict:
        """Writes a multi-value register. Concurrent writes on different nodes are all kept
        and shown as a conflict, never silently resolved. A write over a conflict supersedes
        every value and appends a signed RESOLUTION entry naming them. 422 on an unknown field
        or triage status; 403 on a read-only node."""
        body = await json_object(request)
        try:
            return await node.ops.annotate(event_id, body.get("field"), body.get("value"), operator(request))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/ops/digest", tags=[apidoc.OPERATOR_DATA], summary="Operator-data state digest")
    def ops_digest() -> dict:
        """State digests and version vectors of the log and annotations: two nodes with the
        same digests hold the same operator data. Also lists open conflicts and entries
        rejected for a bad signature."""
        return {**node.ops.digest(), "conflicts": node.ops.conflicts(), "rejected": node.ops.log.rejected}

    # ------------------------------------------------------ link and sync
    @app.get("/api/link", tags=[apidoc.LINK_AND_SYNC], summary="Measured link state")
    def link() -> dict:
        """CONNECTED, DEGRADED, LIMITED, DENIED or UNKNOWN, measured from the sync agent's own
        exchanges (round trip, throughput, failures), never configured. `emulation` appears
        only with demo controls on."""
        out = {"role": settings.role, "hub_id": settings.hub_id, "monitor": node.link.snapshot()}
        if node.toxiproxy is not None and settings.demo_controls:
            try:
                out["emulation"] = node.toxiproxy.status()
            except Exception as exc:  # noqa: BLE001 - report, don't fail the endpoint
                log.warning("Link emulator unreachable", error=type(exc).__name__)
                out["emulation"] = None
        return out

    @app.post(
        "/api/demo/link",
        tags=[apidoc.LINK_AND_SYNC],
        summary="Apply a link-emulation preset (demo only)",
        openapi_extra=apidoc.json_body({"preset": {"enum": sorted(TOXIPROXY_PRESETS)}}, required=("preset",)),
    )
    async def demo_link(request: Request) -> dict:
        """Demonstration and harness only: drives the link emulator. 403 unless demo controls
        are on and the caller is on localhost; 503 without an emulator; 422 on an unknown
        preset."""
        client = request.client.host if request.client else ""
        if not settings.demo_controls or client not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise HTTPException(403, "link emulation controls are disabled on this node")
        if node.toxiproxy is None:
            raise HTTPException(503, "no link emulator configured")
        body = await json_object(request)
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

    @app.get("/api/sync", tags=[apidoc.LINK_AND_SYNC], summary="Sync state")
    def sync_status() -> dict:
        """On an edge: the want-queue in triage order with each item's class, deadline, status
        and ETA, recent arrivals, events held SUMMARY_ONLY, and the last cycle. On a hub:
        request counters."""
        if node.sync_agent is not None:
            return {"role": "edge", **node.sync_agent.status()}
        if node.sync_server is not None:
            return {"role": "hub", "requests": node.sync_server.requests}
        return {"role": settings.role}

    @app.get("/api/quarantine", tags=[apidoc.CONJUNCTIONS], summary="Quarantined CDMs")
    def quarantine() -> list[dict]:
        """Every rejected message with its sha256, rejection code, detail and source. Nothing
        is dropped silently."""
        return node.conjunctions.quarantined()

    @app.get("/api/validation", tags=[apidoc.CONJUNCTIONS], summary="Engine against NASA CARA, computed on this node")
    def validation() -> dict:
        """The deployed engine re-run against NASA CARA's published cases at startup, so a
        node built with a different engine shows it."""
        return node.validation.summary()

    # ------------------------------------------------------------------ SSE
    @app.get(
        "/api/stream",
        tags=[apidoc.STREAM],
        summary="Node-local events (server-sent events)",
        response_class=StreamingResponse,
        responses=apidoc.SSE_RESPONSE,
    )
    async def stream(request: Request) -> StreamingResponse:
        """This node's `node.<node_id>.>` bus events. Local to the node: it keeps working
        when the link to any other node is down. A subscriber that falls 256 events behind
        is never dropped from silently: the node logs it and closes that stream, and the
        console reconnects and re-reads everything when its stream opens."""
        queue: asyncio.Queue[Msg] = asyncio.Queue(maxsize=STREAM_QUEUE_SLOTS)
        overflowed = asyncio.Event()

        async def enqueue(msg: Msg) -> None:
            if overflowed.is_set():
                return  # the stream is closing; the console re-reads everything on reconnect
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                overflowed.set()
                log.warning(
                    "Stream subscriber overflowed",
                    client=request.client.host if request.client else None,
                    slots=STREAM_QUEUE_SLOTS,
                    kind=msg.headers.get("Sentinel-Kind", msg.subject),
                )

        subs = [await node.bus.subscribe(subjects.local_all(settings.node_id), enqueue)]

        async def events_out() -> AsyncIterator[str]:
            try:
                yield "retry: 3000\n\n"
                while not overflowed.is_set() and not await request.is_disconnected():
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
