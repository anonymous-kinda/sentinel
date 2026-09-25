"""The unit: validated on the way in, and kept on this node only (ADR-010).

A unit in the wrong place, or with no time to react, makes every pass and
gap answer wrong, so wrong input raises `UnitRejected` naming the field.
Messages never echo a submitted value: coordinates do not belong in error
text, logs or anywhere else they could be copied from.

The unit is persisted in one JSON file, created with mode 0600 and
replaced atomically. It is never a sync record and never published.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import math
import os
import pathlib
import tempfile
from typing import Any

from .model import MAX_HOURS, Unit

MAX_UNIT_ID_CHARS = 64
# A ground unit sits between the lowest dry land (the Dead Sea shore, about
# -430 m) and the highest summit (8,849 m), with a margin.
MIN_ALT_M = -500.0
MAX_ALT_M = 9000.0
# A gap longer than the longest interval the node computes can never be found.
MAX_REACTION_TIME_MIN = MAX_HOURS * 60.0
FIELDS = tuple(field.name for field in dataclasses.fields(Unit))
DEFAULTS = {f.name: f.default for f in dataclasses.fields(Unit) if f.default is not dataclasses.MISSING}
REQUIRED = tuple(name for name in FIELDS if name not in DEFAULTS)
FILE_MODE = 0o600


class UnitRejected(ValueError):
    def __init__(self, field: str, detail: str):
        super().__init__(f"{field}: {detail}")
        self.field = field
        self.detail = detail


def unit_from_dict(body: Any) -> Unit:
    if not isinstance(body, dict):
        raise UnitRejected("unit", "must be a JSON object")
    unknown = sorted(set(body) - set(FIELDS))
    if unknown:
        raise UnitRejected(unknown[0], "is not a unit field")
    for name in REQUIRED:
        if name not in body:
            raise UnitRejected(name, "is required")
    unit = Unit(
        unit_id=_unit_id(body["unit_id"]),
        lat_deg=_number(body, "lat_deg"),
        lon_deg=_number(body, "lon_deg"),
        alt_m=_number(body, "alt_m"),
        reaction_time_min=_number(body, "reaction_time_min"),
    )
    validate_unit(unit)
    return unit


def unit_to_dict(unit: Unit) -> dict:
    return dataclasses.asdict(unit)


def validate_unit(unit: Unit) -> None:
    if not -90.0 <= unit.lat_deg <= 90.0:
        raise UnitRejected("lat_deg", "must be within [-90, 90]")
    if not -180.0 <= unit.lon_deg <= 180.0:
        raise UnitRejected("lon_deg", "must be within [-180, 180]")
    if not MIN_ALT_M <= unit.alt_m <= MAX_ALT_M:
        raise UnitRejected("alt_m", f"must be within [{MIN_ALT_M:g}, {MAX_ALT_M:g}]")
    if not 0.0 < unit.reaction_time_min <= MAX_REACTION_TIME_MIN:
        raise UnitRejected("reaction_time_min", f"must be positive and at most {MAX_REACTION_TIME_MIN:g}")


def _unit_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UnitRejected("unit_id", "must be a non-blank string")
    if len(value) > MAX_UNIT_ID_CHARS:
        raise UnitRejected("unit_id", f"must be at most {MAX_UNIT_ID_CHARS} characters")
    return value


def _number(body: dict, name: str) -> float:
    value = body[name] if name in body else DEFAULTS[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise UnitRejected(name, "must be a finite number")
    return float(value)


class UnitFile:
    """The one place a unit is stored: a private file on this node."""

    def __init__(self, path: pathlib.Path):
        self.path = pathlib.Path(path)

    def load(self) -> Unit | None:
        try:
            text = self.path.read_text()
        except FileNotFoundError:
            return None
        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            raise UnitRejected("unit", "stored unit is not JSON") from exc
        return unit_from_dict(body)

    def save(self, unit: Unit) -> None:
        """Write a private temporary file beside the target, then rename it
        over the target: a reader sees the old unit or the new, never half."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=self.path.parent, prefix=".unit-", suffix=".tmp")
        try:
            os.fchmod(fd, FILE_MODE)
            with os.fdopen(fd, "w") as fh:
                json.dump(unit_to_dict(unit), fh)
            os.replace(temp, self.path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp)
            raise

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
