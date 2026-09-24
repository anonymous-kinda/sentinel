"""Wayfinder ephemeris adapter, written against an ASSUMED schema.

Wayfinder is a space-object product of Privateer Space that offers
ephemeris download through an API. Sentinel is not affiliated with or
endorsed by Privateer Space. Wayfinder's schema is not public to this
project, so this adapter parses a shape Sentinel ASSUMED, and it must be
validated against the real API when access is granted. See
docs/adapters/wayfinder.md.

ASSUMED payload (JSON):

    {
      "object": {"norad_id": 40115, "name": "WORLDVIEW-3 (WV-3)"},
      "frame": "ITRF",                          Earth-fixed; ITRF realisations only
      "time_system": "UTC",
      "created": "2026-09-23T22:37:02.779392Z", when the product was made
      "epochs": ["2026-09-24T05:00:00Z", ...],  ISO 8601, with a zone
      "positions_km": [[x, y, z], ...]          one row per epoch, km
    }

Unknown keys are ignored, so a richer real payload still parses. A missing
or mistyped field raises SCHEMA_MISMATCH; a wrong frame, time system or
epoch order raises the shared ephemeris codes (sentinel.ephemeris.table).

To swap in the real schema: change parse_ephemeris (the only function that
knows the shape), replace the fixture with a real response, and keep
tests/adapters/test_wayfinder.py passing. Nothing downstream changes: it
sees a StateTable.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from typing import Any

import numpy as np

from sentinel.ephemeris.table import EphemerisRejected, StateTable, require_earth_fixed, require_utc
from sentinel.obs import get_logger

log = get_logger(__name__)

SCHEMA_STATUS = "ASSUMED"
ADAPTER = "wayfinder"


def _mismatch(detail: str) -> EphemerisRejected:
    return EphemerisRejected("SCHEMA_MISMATCH", f"{detail} (assumed Wayfinder schema)")


def _field(mapping: Any, key: str, kind: type, where: str) -> Any:
    if not isinstance(mapping, Mapping) or key not in mapping:
        raise _mismatch(f"{where}{key} is missing")
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, kind):
        raise _mismatch(f"{where}{key} is {type(value).__name__}, expected {kind.__name__}")
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _time(text: Any, where: str) -> dt.datetime:
    if not isinstance(text, str):
        raise _mismatch(f"{where} is {type(text).__name__}, expected an ISO 8601 string")
    try:
        when = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise EphemerisRejected("MALFORMED_TIME", f"{where}: {text!r} is not ISO 8601") from exc
    return when if when.tzinfo is None else when.astimezone(dt.UTC)


def _position(row: Any, index: int) -> tuple[float, float, float]:
    if not (isinstance(row, list) and len(row) == 3 and all(_is_number(v) for v in row)):
        raise _mismatch(f"positions_km[{index}] is not three numbers")
    x, y, z = row
    return float(x), float(y), float(z)


def parse_ephemeris(payload: Mapping[str, Any]) -> StateTable:
    """Map one ephemeris payload in the assumed schema to a StateTable."""
    obj = _field(payload, "object", Mapping, "")
    norad_id = _field(obj, "norad_id", int, "object.")
    require_earth_fixed(_field(payload, "frame", str, ""))
    require_utc(_field(payload, "time_system", str, ""))
    epochs = _field(payload, "epochs", list, "")
    rows = _field(payload, "positions_km", list, "")
    table = StateTable(
        norad_id=norad_id,
        name=_field(obj, "name", str, "object."),
        epochs=tuple(_time(text, f"epochs[{i}]") for i, text in enumerate(epochs)),
        positions_km=np.array([_position(row, i) for i, row in enumerate(rows)], dtype=float).reshape(-1, 3),
        created=_time(_field(payload, "created", str, ""), "created"),
    )
    log.info("Ephemeris parsed from assumed schema", adapter=ADAPTER, norad_id=norad_id, states=len(table.epochs))
    return table


def load_ephemeris(data: bytes) -> StateTable:
    """Parse a raw JSON response body."""
    try:
        payload = json.loads(data)
    except ValueError as exc:
        raise _mismatch("body is not JSON") from exc
    if not isinstance(payload, Mapping):
        raise _mismatch("body is not a JSON object")
    return parse_ephemeris(payload)
