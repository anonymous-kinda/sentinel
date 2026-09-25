"""Every write route, enumerated from the app's own router.

The lists are read from `app.routes`, not written down here, so a route a
later module adds is covered the moment it is registered: it refuses on a
read-only node, it answers a malformed body with a 4xx, and it never reads
more than the node's body limit.
"""

import asyncio
import datetime as dt
import re
import tempfile

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from sentinel.api import create_app
from sentinel.api.bodies import MAX_BODY_BYTES, READ_ONLY_SAFE
from sentinel.api.settings import Settings
from sentinel.clock import FixedClock

NOW = dt.datetime(2026, 9, 23, 13, 0, tzinfo=dt.UTC)
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# The only POST that changes no node data: a question carries a body.
EXPECTED_READ_ONLY_SAFE = {("POST", "/api/ai/ask")}


def build_app(var_dir, **overrides):
    # Every optional surface on, so no route hides behind a disabled feature.
    settings = Settings(
        exercise=False, library=False, web_dist=None, var_dir=str(var_dir), ai=True, demo_controls=True, **overrides
    )
    return create_app(settings, clock=FixedClock(NOW), start_background=False)


def _routes(app) -> list[APIRoute]:
    return [route for route in app.routes if isinstance(route, APIRoute)]


def _write_routes() -> list[tuple[str, str]]:
    with tempfile.TemporaryDirectory() as var_dir:
        app = build_app(var_dir)
        return sorted((method, route.path) for route in _routes(app) for method in route.methods & MUTATING)


def _read_only_safe(app) -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in _routes(app)
        for method in route.methods & MUTATING
        if getattr(route.endpoint, READ_ONLY_SAFE, False)
    }


WRITE_ROUTES = _write_routes()


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "EX-1", path)


@pytest.fixture
def writable(tmp_path):
    with TestClient(build_app(tmp_path), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def read_only(tmp_path):
    with TestClient(build_app(tmp_path, read_only=True), raise_server_exceptions=False) as client:
        yield client


def test_the_enumeration_sees_every_module_that_writes():
    paths = {path for _, path in WRITE_ROUTES}
    assert {"/api/ingest/cdm", "/api/events/{event_id}/decision", "/api/ai/confirm",
            "/api/passes/unit", "/api/screening", "/api/demo/link"} <= paths


def test_exempting_a_write_route_from_read_only_is_a_visible_decision(tmp_path):
    assert _read_only_safe(build_app(tmp_path)) == EXPECTED_READ_ONLY_SAFE


@pytest.mark.parametrize("method,path", [r for r in WRITE_ROUTES if r not in EXPECTED_READ_ONLY_SAFE])
def test_a_read_only_node_refuses_every_write(read_only, method, path):
    r = read_only.request(method, concrete(path), content=b"{}", headers={"content-type": "application/json"})
    assert r.status_code == 403, r.text
    assert r.json()["detail"] == "this node is read-only"


@pytest.mark.parametrize("body", [b"{not json", b"[]", b'"text"', b"\xff\xfe", b"[" * 100_000], ids=[
    "not-json", "array", "string", "not-utf8", "deeply-nested",
])
@pytest.mark.parametrize("method,path", WRITE_ROUTES)
def test_a_malformed_body_is_a_client_error_never_a_server_error(writable, method, path, body):
    r = writable.request(method, concrete(path), content=body, headers={"content-type": "application/json"})
    assert r.status_code < 500, f"{method} {path}: {r.status_code} {r.text[:200]}"


@pytest.mark.parametrize("method,path", WRITE_ROUTES)
def test_a_body_over_the_limit_is_refused_on_every_write_route(writable, method, path):
    body = b'{"text": "' + b"x" * MAX_BODY_BYTES + b'"}'
    r = writable.request(method, concrete(path), content=body, headers={"content-type": "application/json"})
    assert r.status_code == 413, f"{method} {path}: {r.status_code}"


def test_an_unannounced_oversized_body_is_not_read_to_the_end(tmp_path):
    """A chunked upload with no Content-Length is cut off at the limit, not
    buffered whole and measured afterwards: a node on a small edge box must
    not be made to hold an attacker's gigabyte in memory."""
    app = build_app(tmp_path)
    chunk = b"x" * (MAX_BODY_BYTES // 2 + 1)
    pulled, sent = asyncio.run(_post_chunks(app, "/api/ingest/cdm", [chunk] * 8))
    assert sent[0]["status"] == 413
    assert pulled <= 3, f"read {pulled} chunks of {len(chunk)} bytes before refusing"


async def _post_chunks(app, path: str, chunks: list[bytes]) -> tuple[int, list[dict]]:
    pulled = 0
    sent: list[dict] = []

    async def receive():
        nonlocal pulled
        if pulled < len(chunks):
            pulled += 1
            return {"type": "http.request", "body": chunks[pulled - 1], "more_body": pulled < len(chunks)}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"content-type", b"text/plain")],
        "server": ("testserver", 80), "client": ("127.0.0.1", 50000),
    }
    await app(scope, receive, send)
    return pulled, sent
