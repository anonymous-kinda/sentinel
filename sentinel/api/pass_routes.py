"""The pass module's HTTP surface (M3): docs/icd/passes-api.md, exactly.

    GET    /api/passes/unit       200 Unit | 404 no unit
    PUT    /api/passes/unit       200 Unit | 422 wrong input | 403 read-only
    DELETE /api/passes/unit       204 | 403 read-only
    GET    /api/passes?hours=24   windows and gaps (1-72 h) | 409 no unit
    GET    /api/passes/catalog    imagers paired with element sets, and skipped
    GET    /api/passes/tracks     ECEF metres for the globe (visualization only)

Edge-local (ADR-010): everything is computed from this node's own element
sets for this node's own unit. Nothing here calls another node, and the
only bus message is the service's coordinate-free passes.updated.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

from fastapi import FastAPI, HTTPException, Query, Request, Response

from ..obs import get_logger
from ..passes.catalog import load_catalog
from ..passes.elements import ElementSetError, Skipped
from ..passes.gaps import GAP_LABEL, Gap
from ..passes.model import PassWindow
from ..passes.service import MAX_HOURS, MIN_HOURS, CatalogEntry, NoUnit, PassReport, PassService
from ..passes.tracks import STEP_S, ecef_track_m
from ..passes.unit import UnitFile, UnitRejected, unit_from_dict, unit_to_dict

log = get_logger(__name__)

UNIT_FILE = "unit.json"


def register(app: FastAPI, node) -> None:
    settings = node.settings
    service = PassService(
        node.elements,
        load_catalog(),
        node.clock,
        UnitFile(pathlib.Path(settings.var_dir) / UNIT_FILE),
        node.bus,
        settings.node_id,
    )
    node.extensions["passes"] = service
    node.extensions.setdefault("modules", []).append("passes")
    node.extensions.setdefault("elements_changed", []).append(lambda _node: service.elements_changed())

    def writable() -> None:
        if settings.read_only:
            raise HTTPException(403, "this node is read-only")

    @app.get("/api/passes/unit")
    def get_unit() -> dict:
        if service.unit is None:
            raise HTTPException(404, "no unit is set on this node")
        return unit_to_dict(service.unit)

    @app.put("/api/passes/unit")
    async def put_unit(request: Request) -> dict:
        writable()
        try:
            unit = unit_from_dict(await _json_body(request))
        except UnitRejected as exc:
            raise HTTPException(422, {"field": exc.field, "reason": exc.detail}) from exc
        await service.set_unit(unit)
        return unit_to_dict(unit)

    @app.delete("/api/passes/unit", status_code=204)
    async def delete_unit() -> Response:
        writable()
        await service.clear_unit()
        return Response(status_code=204)

    @app.get("/api/passes")
    def passes(hours: float = Query(24.0, ge=MIN_HOURS, le=MAX_HOURS)) -> dict:
        try:
            return _report(service.passes(hours))
        except NoUnit as exc:
            raise HTTPException(409, "no unit is set on this node; PUT /api/passes/unit first") from exc
        except ElementSetError as exc:
            log.warning("Pass computation refused", error=str(exc))
            raise HTTPException(503, "an element set for a catalogued imager cannot be used") from exc

    @app.get("/api/passes/catalog")
    def catalog() -> dict:
        entries, skipped = service.catalog()
        return {"imagers": [_catalog_entry(e) for e in entries], "skipped": [_skipped(s) for s in skipped]}

    @app.get("/api/passes/tracks")
    def tracks(norad_id: int, start: dt.datetime, end: dt.datetime) -> dict:
        element_set = node.elements.latest().get(norad_id)
        if element_set is None:
            raise HTTPException(404, "no element set for this object on this node")
        try:
            positions = ecef_track_m(element_set, start, end)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"norad_id": norad_id, "positions_ecef_m": positions, "step_s": STEP_S, "note": "visualization only"}


async def _json_body(request: Request):
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise UnitRejected("unit", "body is not JSON") from exc


# ------------------------------------------------------------ serialization
def _report(report: PassReport) -> dict:
    return {
        "unit": unit_to_dict(report.unit),
        "start": report.start.isoformat(),
        "end": report.end.isoformat(),
        "provider": report.provider,
        "label": GAP_LABEL,
        "windows": [_window(w) for w in report.windows],
        "gaps": [_gap(g) for g in report.gaps],
        "next_unobserved": None if report.next_unobserved is None else _gap(report.next_unobserved),
        "catalog": {"imagers": len(report.imagers), "skipped": [_skipped(s) for s in report.skipped]},
        "elements": {
            "oldest_age_days": report.elements.oldest_age_days,
            "newest_age_days": report.elements.newest_age_days,
            "stale": report.elements.stale,
        },
    }


def _window(window: PassWindow) -> dict:
    padded_start, padded_end = window.padded
    return {
        "norad_id": window.norad_id,
        "name": window.name,
        "sensor": window.sensor,
        "rise": window.rise.isoformat(),
        "culmination": window.culmination.isoformat(),
        "set": window.set.isoformat(),
        "padded_start": padded_start.isoformat(),
        "padded_end": padded_end.isoformat(),
        "pad_s": window.pad_s,
        "max_elevation_deg": window.max_elevation_deg,
        "mask_elevation_deg": window.mask_elevation_deg,
        "element_age_days": window.element_age_days,
        "stale": window.stale,
        "sunlit": window.sunlit,
        "usable": window.usable,
    }


def _gap(gap: Gap) -> dict:
    return {
        "start": gap.start.isoformat(),
        "end": gap.end.isoformat(),
        "duration_s": gap.duration_s,
        "low_confidence": gap.low_confidence,
    }


def _skipped(skipped: Skipped) -> dict:
    return {"norad_id": skipped.imager.norad_id, "name": skipped.imager.name, "reason": skipped.reason.value}


def _catalog_entry(entry: CatalogEntry) -> dict:
    imager = entry.imager
    return {
        "norad_id": imager.norad_id,
        "name": entry.object_name,
        "sensor": imager.sensor,
        "max_off_nadir_deg": imager.max_off_nadir_deg,
        "gsd_m": imager.gsd_m,
        "basis": imager.basis,
        "element_epoch": entry.element_epoch.isoformat(),
        "element_age_days": entry.element_age_days,
        "stale": entry.stale,
    }
