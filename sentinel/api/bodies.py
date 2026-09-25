"""What a write request may carry, enforced once for every route.

Three rules, each applied to the whole app rather than route by route, so a
route a later module registers is covered without remembering to be:

  * a read-only node refuses every POST, PUT, PATCH and DELETE, except a
    route whose endpoint is marked `read_only_safe`: it changes no node data;
  * no request body over MAX_BODY_BYTES is read, announced or not;
  * a JSON body that is not JSON, or not an object, is a 422, never a 500.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# A CDM is a few kilobytes and every JSON body here is smaller still.
MAX_BODY_BYTES = 1_000_000
TOO_LARGE = "a request body is at most 1 MB; a CDM is a few kilobytes"
# The endpoint attribute marking the rare POST that changes no node data.
READ_ONLY_SAFE = "read_only_safe"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# ------------------------------------------------------------- read-only
def read_only_safe(endpoint: Callable) -> Callable:
    """Mark an endpoint that takes a body but changes no node data (a
    question), so a read-only node still serves it."""
    setattr(endpoint, READ_ONLY_SAFE, True)
    return endpoint


def refuse_writes_on_read_only(request: Request) -> None:
    """An app-wide dependency: runs before every route's own code."""
    if request.method not in WRITE_METHODS or not request.app.state.node.settings.read_only:
        return
    endpoint = getattr(request.scope.get("route"), "endpoint", None)
    if getattr(endpoint, READ_ONLY_SAFE, False):
        return
    raise HTTPException(403, "this node is read-only")


# ------------------------------------------------------------ body limit
class BodyLimit:
    """ASGI middleware: refuse an announced oversized body before reading
    it, and stop reading an unannounced one at the limit."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in WRITE_METHODS:
            await self.app(scope, receive, send)
            return
        if _announced_length(scope) > self.max_bytes:
            await JSONResponse({"detail": TOO_LARGE}, status_code=413)(scope, receive, send)
            return
        await self.app(scope, self._limited(receive), send)

    def _limited(self, receive: Receive) -> Receive:
        received = 0

        async def limited() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(413, TOO_LARGE)
            return message

        return limited


def _announced_length(scope: Scope) -> int:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return 0
    return 0


# ------------------------------------------------------------------ JSON
def parse_json(raw: bytes) -> Any:
    """Raises ValueError("body is not JSON") for anything json cannot read,
    including nesting deep enough to exhaust the parser's recursion."""
    try:
        return json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise ValueError("body is not JSON") from exc


async def json_object(request: Request) -> dict:
    try:
        body = parse_json(await request.body())
    except ValueError as exc:
        raise HTTPException(422, "body is not JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(422, "body must be a JSON object")
    return body
