"""OpenAPI metadata: tags, and bodies for routes that read their own request.

Documentation only. Most write routes read `request.json()` or
`request.body()` directly, so FastAPI cannot infer a request schema; these
declarations describe the interface without changing what a route accepts
or how it answers. docs/icd/openapi.json is exported from the app with them
(scripts/export_openapi.py).
"""

from __future__ import annotations

NODE = "node"
CONJUNCTIONS = "conjunctions"
OPERATOR_DATA = "operator data"
LINK_AND_SYNC = "link and sync"
STREAM = "stream"
ASSISTANT = "assistant"
SCREENING = "screening"


def json_body(properties: dict, required: tuple[str, ...] = ()) -> dict:
    """An `openapi_extra` declaring a JSON object request body."""
    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    return {"requestBody": {"required": True, "content": {"application/json": {"schema": schema}}}}


def text(description: str) -> dict:
    return {"type": "string", "description": description}


DESCRIPTION = (
    "The HTTP interface of one Sentinel node: hub, edge or standalone. Every node serves "
    "its own console from its own data (ADR-009), so nothing here depends on the link to "
    "another node. Times are ISO 8601 UTC and units are field-name suffixes "
    "(`_m`, `_m_s`, `_km`, `_s`). A read-only node answers every write with 403. The acting "
    "operator is named by the `X-Sentinel-Operator` header, set by the front proxy. "
    "Interface control documents: docs/icd/README.md."
)

TAGS = [
    {"name": NODE, "description": "Identity, role, clock, marking and loaded modules."},
    {
        "name": CONJUNCTIONS,
        "description": "CDM admission (docs/icd/cdm-profile.md) and the assessed events built from it. "
        "A Pc never appears without its `method`.",
    },
    {
        "name": OPERATOR_DATA,
        "description": "The signed decision log and per-event annotations, replicated between nodes as CRDTs.",
    },
    {
        "name": LINK_AND_SYNC,
        "description": "The measured link to the hub and the priority-pull sync state (docs/icd/sync-envelope.md).",
    },
    {
        "name": STREAM,
        "description": "Server-sent events: this node's node-local bus events (docs/icd/asyncapi.yaml).",
    },
    {
        "name": ASSISTANT,
        "description": "AI decision support (ADR-007). Routes to tools and phrases their facts; it never computes a Pc.",
    },
    {
        "name": SCREENING,
        "description": "Demonstration mode (ADR-002): element-set geometry filed as DERIVED CDMs, never a Pc "
        "(docs/icd/screening-api.md).",
    },
]

KVN_BODY = {
    "requestBody": {
        "required": True,
        "description": "One CCSDS 508.0-B-1 CDM in KVN, UTF-8 or ASCII, at most 1 MB.",
        "content": {"text/plain": {"schema": {"type": "string"}}},
    }
}

_NULLABLE_TEXT = {"type": ["string", "null"]}
_INGEST_RESULT = {
    "application/json": {
        "schema": {
            "type": "object",
            "required": ["status", "sha256"],
            "properties": {
                "status": {"enum": ["accepted", "duplicate", "rejected"]},
                "sha256": text("of the bytes as received"),
                "event_id": {**_NULLABLE_TEXT, "description": "the event the CDM joined (accepted only)"},
                "code": {**_NULLABLE_TEXT, "description": "rejection code (docs/icd/cdm-profile.md)"},
                "detail": _NULLABLE_TEXT,
                "warnings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": text("warning code (docs/icd/cdm-profile.md)"),
                            "detail": text("what was found"),
                            "key": _NULLABLE_TEXT,
                            "object_index": {"type": ["integer", "null"], "description": "0 = OBJECT1, 1 = OBJECT2"},
                        },
                    },
                },
            },
        }
    }
}

INGEST_RESPONSES = {
    201: {
        "description": "Accepted and assessed. `warnings` lists anything that limits what can be concluded.",
        "content": _INGEST_RESULT,
    },
    200: {
        "description": "Duplicate: these exact bytes (same sha256) were already admitted. No change.",
        "content": _INGEST_RESULT,
    },
    403: {"description": "This node is read-only."},
    413: {"description": "Larger than 1 MB. A CDM is a few kilobytes."},
    422: {
        "description": "Rejected and quarantined, with a `code` from docs/icd/cdm-profile.md.",
        "content": _INGEST_RESULT,
    },
}

SSE_RESPONSE = {
    200: {
        "description": "`text/event-stream`. Each event is named by its `Sentinel-Kind` header "
        "(`cdm.accepted`, `sync.progress`, ...) and carries the bus payload as JSON. "
        "A `: keepalive` comment is sent every 15 s of silence.",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}

