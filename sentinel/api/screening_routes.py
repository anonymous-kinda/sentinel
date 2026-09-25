"""Demonstration-mode screening over HTTP (ADR-002): docs/icd/screening-api.md.

    POST /api/screening  {primary_norad_id, hours, threshold_km}

Screens the primary against every element set on this node, then ingests
each close approach as a DERIVED CDM through the ordinary conjunction path.
The CDM carries no covariance, so the engine's existing NO_COVARIANCE gate
refuses a Pc: there is no screening branch anywhere in the engine, and no
probability in this response.
"""

from __future__ import annotations

import dataclasses
import math

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..cdm import emit
from ..obs import get_logger
from ..screening.derived_cdm import derived_cdm, nearest_millisecond
from ..screening.screen import CloseApproach, ScreeningRefused, ScreeningResult, screen
from . import apidoc
from .bodies import json_object

log = get_logger(__name__)

SOURCE = "api-screening"
FIELDS = ("primary_norad_id", "hours", "threshold_km")
DEFAULTS = {"hours": 24, "threshold_km": 5}
LIMITS = {"hours": (0.0, 72.0), "threshold_km": (0.0, 50.0)}     # (exclusive, inclusive)
NOTE = "element-set geometry only; no probability of collision (ADR-002)"


@dataclasses.dataclass(frozen=True)
class ScreeningRequest:
    primary_norad_id: int
    hours: float
    threshold_km: float


def register(app: FastAPI, node) -> None:
    @app.post(
        "/api/screening",
        tags=[apidoc.SCREENING],
        summary="Screen a primary against this node's element sets (no Pc)",
        openapi_extra=apidoc.json_body(
            {
                "primary_norad_id": {"type": "integer", "minimum": 1},
                "hours": {"type": "number", "default": DEFAULTS["hours"], "exclusiveMinimum": LIMITS["hours"][0],
                          "maximum": LIMITS["hours"][1]},
                "threshold_km": {"type": "number", "default": DEFAULTS["threshold_km"],
                                 "exclusiveMinimum": LIMITS["threshold_km"][0], "maximum": LIMITS["threshold_km"][1]},
            },
            required=("primary_norad_id",),
        ),
    )
    async def screening(request: Request) -> dict:
        """Close approaches to the primary over the next `hours`, each filed as a DERIVED CDM
        with no covariance, so the engine refuses its Pc. 404 when this node has no element
        set for the primary; 422 on wrong input; 403 on a read-only node. See
        docs/icd/screening-api.md."""
        asked = _request(await json_object(request))
        elements = node.elements.latest()
        start = node.clock.now()
        try:
            result = await run_in_threadpool(
                screen, asked.primary_norad_id, elements, start, asked.hours, asked.threshold_km
            )
        except ScreeningRefused as exc:
            status = 404 if exc.code == "UNKNOWN_PRIMARY" else 422
            raise HTTPException(status, {"code": exc.code, "reason": exc.detail}) from exc
        approaches = [await _ingest(node, result, approach, elements) for approach in result.approaches]
        log.info(
            "Screening ingested",
            primary_id=asked.primary_norad_id,
            approaches=len(approaches),
            accepted=sum(a["ingest"] == "accepted" for a in approaches),
        )
        return _response(asked, result, approaches)


def _request(body: dict) -> ScreeningRequest:
    unknown = sorted(set(body) - set(FIELDS))
    if unknown:
        raise HTTPException(422, f"{unknown[0]} is not a screening field")
    primary = body.get("primary_norad_id")
    if isinstance(primary, bool) or not isinstance(primary, int) or primary <= 0:
        raise HTTPException(422, "primary_norad_id must be a positive integer")
    return ScreeningRequest(primary, _bounded(body, "hours"), _bounded(body, "threshold_km"))


def _bounded(body: dict, name: str) -> float:
    value = body.get(name, DEFAULTS[name])
    low, high = LIMITS[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise HTTPException(422, f"{name} must be a number")
    if not low < value <= high:
        raise HTTPException(422, f"{name} must be in ({low:g}, {high:g}]")
    return value


async def _ingest(node, result: ScreeningResult, approach: CloseApproach, elements: dict) -> dict:
    message = derived_cdm(result, approach, elements, node.clock.now())
    ingested = await node.conjunctions.ingest(emit(message).encode(), SOURCE, "DERIVED")
    event_id = ingested.event_id or _event_of(node, ingested.sha256)
    summary = node.conjunctions.event_summary(event_id) if event_id else None
    return {
        "secondary": {"norad_id": approach.secondary_id, "name": approach.secondary_name},
        "tca": nearest_millisecond(approach.tca).isoformat(),
        "miss_distance_km": approach.miss_distance_km,
        "relative_speed_km_s": approach.relative_speed_km_s,
        "event_id": event_id,
        "ingest": ingested.status,
        "data_class": None if summary is None else summary["data_class"],
        "assessment": None if summary is None else {
            "method": summary["assessment"]["method"],
            "refusal_reason": summary["assessment"]["refusal_reason"],
        },
    }


def _event_of(node, sha256: str) -> str | None:
    """A duplicate CDM is already filed under an event: report that one."""
    row = node.conjunctions.store.cdm(sha256)
    return None if row is None else row.event_id


def _response(asked: ScreeningRequest, result: ScreeningResult, approaches: list[dict]) -> dict:
    return {
        "mode": "DEMONSTRATION",
        "note": NOTE,
        "primary": {"norad_id": result.primary_id, "name": result.primary_name},
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "hours": asked.hours,
        "threshold_km": asked.threshold_km,
        "screened": result.secondaries,
        "after_prefilter": result.after_prefilter,
        "runtime_s": round(result.runtime_s, 3),
        "approaches": approaches,
        "skipped": [{"norad_id": s.norad_id, "code": s.code, "detail": s.detail} for s in result.skipped],
    }
