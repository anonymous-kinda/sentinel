"""Who is acting. Operator identity comes from the front proxy's header."""

from __future__ import annotations

from fastapi import Request

OPERATOR_HEADER = "X-Sentinel-Operator"


def operator_of(request: Request, node_id: str) -> str:
    return request.headers.get(OPERATOR_HEADER) or f"operator@{node_id}"
