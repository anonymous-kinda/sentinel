"""CCSDS Orbit Ephemeris Message (502.0-B-3), KVN: codec and admission.

The codec covers the subset a pass provider needs, and refuses the rest
with a stable code rather than silently ignoring it:

    header    CCSDS_OEM_VERS, CREATION_DATE, ORIGINATOR
    metadata  OBJECT_NAME, OBJECT_ID, CENTER_NAME, REF_FRAME, TIME_SYSTEM,
              START_TIME, STOP_TIME, optional INTERPOLATION, INTERPOLATION_DEGREE
    data      epoch x y z [vx vy vz [ax ay az]]      km, km/s, km/s**2
    refused   a second segment, any other keyword (USEABLE_START_TIME narrows
              where data may be used), covariance blocks

COMMENT lines are accepted and not kept. parse(emit(m)) == m: epochs are
written to the microsecond (a millisecond is 7.6 m along-track in LEO) and
numbers with every digit. Times are read by the CCSDS 301.0 time-code parser
the CDM codec already uses (sentinel.cdm.timefmt).

admit() is the admission policy that turns a message into a StateTable:
wrong raises (not Earth-centred, not ITRF, not UTC, epochs out of order,
catalog number contradicted); incomplete degrades with a warning (states
without velocities are standard-violating but still usable, because the
pass provider interpolates positions alone).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re

import numpy as np

from sentinel.cdm.timefmt import parse_ccsds_time
from sentinel.obs import get_logger

from .table import EphemerisRejected, EphemerisWarning, StateTable, require_earth_fixed, require_utc

log = get_logger(__name__)

HEADER_KEYS = ("CCSDS_OEM_VERS", "CREATION_DATE", "ORIGINATOR")
REQUIRED_META_KEYS = (
    "OBJECT_NAME", "OBJECT_ID", "CENTER_NAME", "REF_FRAME", "TIME_SYSTEM", "START_TIME", "STOP_TIME",
)
OPTIONAL_META_KEYS = ("INTERPOLATION", "INTERPOLATION_DEGREE")
_STATE_WIDTHS = (4, 7, 10)  # epoch + position [+ velocity [+ acceleration]]

_KEYWORD = re.compile(r"^(?P<key>[A-Z][A-Z0-9_]*)\s*=\s*(?P<value>.*?)\s*$")
_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_INTEGER = re.compile(r"^\d+$")

Vector = tuple[float, float, float]


@dataclasses.dataclass(frozen=True)
class OemState:
    epoch: dt.datetime
    position_km: Vector
    velocity_km_s: Vector | None = None
    acceleration_km_s2: Vector | None = None


@dataclasses.dataclass(frozen=True)
class OemMetadata:
    object_name: str
    object_id: str
    center_name: str
    ref_frame: str
    time_system: str
    start_time: dt.datetime
    stop_time: dt.datetime
    interpolation: str | None = None
    interpolation_degree: int | None = None


@dataclasses.dataclass(frozen=True)
class OemMessage:
    version: str
    creation_date: dt.datetime
    originator: str
    metadata: OemMetadata
    states: tuple[OemState, ...]


@dataclasses.dataclass(frozen=True)
class Admission:
    table: StateTable
    warnings: tuple[EphemerisWarning, ...]


# --- parse ---------------------------------------------------------------------

def _time(text: str, where: str) -> dt.datetime:
    try:
        return parse_ccsds_time(text)
    except ValueError as exc:
        raise EphemerisRejected("MALFORMED_TIME", f"{where}: {text!r} is not a CCSDS time") from exc


def _number(text: str, where: str) -> float:
    if not _NUMBER.match(text):
        raise EphemerisRejected("MALFORMED_NUMBER", f"{where}: {text!r} is not a number")
    return float(text)


def _integer(text: str | None, where: str) -> int | None:
    if text is None:
        return None
    if not _INTEGER.match(text):
        raise EphemerisRejected("MALFORMED_NUMBER", f"{where}: {text!r} is not an integer")
    return int(text)


def _keyword(line: str, lineno: int) -> tuple[str, str]:
    match = _KEYWORD.match(line)
    if not match or not match["value"]:
        raise EphemerisRejected("MALFORMED_LINE", f"line {lineno}: not a KEYWORD = value line")
    return match["key"], match["value"]


def _state(line: str, lineno: int) -> OemState:
    tokens = line.split()
    if len(tokens) not in _STATE_WIDTHS:
        raise EphemerisRejected(
            "MALFORMED_LINE", f"line {lineno}: {len(tokens)} values; a state line has 4, 7 or 10"
        )
    where = f"line {lineno}"
    numbers = [_number(token, where) for token in tokens[1:]]
    vectors = [tuple(numbers[i:i + 3]) for i in range(0, len(numbers), 3)]
    return OemState(_time(tokens[0], where), *vectors)


def _store(block: dict[str, str], allowed: tuple[str, ...], key: str, value: str, lineno: int) -> None:
    if key not in allowed:
        raise EphemerisRejected("UNSUPPORTED_KEYWORD", f"line {lineno}: {key} is outside the supported OEM subset")
    if key in block:
        raise EphemerisRejected("DUPLICATE_KEYWORD", f"line {lineno}: {key} appears twice")
    block[key] = value


def _require(block: dict[str, str], keys: tuple[str, ...]) -> None:
    missing = [key for key in keys if key not in block]
    if missing:
        raise EphemerisRejected("MISSING_KEYWORD", f"missing {', '.join(missing)}")


def _metadata(meta: dict[str, str]) -> OemMetadata:
    _require(meta, REQUIRED_META_KEYS)
    return OemMetadata(
        object_name=meta["OBJECT_NAME"],
        object_id=meta["OBJECT_ID"],
        center_name=meta["CENTER_NAME"],
        ref_frame=meta["REF_FRAME"],
        time_system=meta["TIME_SYSTEM"],
        start_time=_time(meta["START_TIME"], "START_TIME"),
        stop_time=_time(meta["STOP_TIME"], "STOP_TIME"),
        interpolation=meta.get("INTERPOLATION"),
        interpolation_degree=_integer(meta.get("INTERPOLATION_DEGREE"), "INTERPOLATION_DEGREE"),
    )


def parse(text: str) -> OemMessage:
    """Parse OEM KVN text. Raises EphemerisRejected with a stable code."""
    header: dict[str, str] = {}
    meta: dict[str, str] = {}
    states: list[OemState] = []
    section = "header"
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("COMMENT"):
            continue
        if line == "META_START":
            if section != "header":
                raise EphemerisRejected("UNSUPPORTED_SEGMENTS", f"line {lineno}: only one segment is supported")
            section = "meta"
        elif line == "META_STOP" and section == "meta":
            section = "data"
        elif line == "COVARIANCE_START":
            raise EphemerisRejected("UNSUPPORTED_BLOCK", f"line {lineno}: covariance is outside the supported subset")
        elif section == "data":
            states.append(_state(line, lineno))
        else:
            key, value = _keyword(line, lineno)
            if section == "header" and not header and key != "CCSDS_OEM_VERS":
                raise EphemerisRejected("NOT_AN_OEM", f"line {lineno}: first keyword is {key}, not CCSDS_OEM_VERS")
            if section == "header":
                _store(header, HEADER_KEYS, key, value, lineno)
            else:
                _store(meta, REQUIRED_META_KEYS + OPTIONAL_META_KEYS, key, value, lineno)

    if "CCSDS_OEM_VERS" not in header:
        raise EphemerisRejected("NOT_AN_OEM", "no CCSDS_OEM_VERS")
    _require(header, HEADER_KEYS)
    return OemMessage(
        version=header["CCSDS_OEM_VERS"],
        creation_date=_time(header["CREATION_DATE"], "CREATION_DATE"),
        originator=header["ORIGINATOR"],
        metadata=_metadata(meta),
        states=tuple(states),
    )


def parse_bytes(data: bytes) -> OemMessage:
    """Parse raw bytes (UTF-8 or ASCII, optional BOM)."""
    return parse(data.decode("utf-8-sig"))


# --- emit ----------------------------------------------------------------------

def _format_time(when: dt.datetime) -> str:
    return when.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _format_state(state: OemState) -> str:
    vectors = (state.position_km, state.velocity_km_s, state.acceleration_km_s2)
    numbers = [repr(value) for vector in vectors if vector is not None for value in vector]
    return " ".join([_format_time(state.epoch), *numbers])


def _metadata_lines(meta: OemMetadata) -> list[str]:
    items = [
        ("OBJECT_NAME", meta.object_name),
        ("OBJECT_ID", meta.object_id),
        ("CENTER_NAME", meta.center_name),
        ("REF_FRAME", meta.ref_frame),
        ("TIME_SYSTEM", meta.time_system),
        ("START_TIME", _format_time(meta.start_time)),
        ("STOP_TIME", _format_time(meta.stop_time)),
        ("INTERPOLATION", meta.interpolation),
        ("INTERPOLATION_DEGREE", meta.interpolation_degree),
    ]
    return [f"{key} = {value}" for key, value in items if value is not None]


def emit(message: OemMessage) -> str:
    """Serialise to OEM KVN. parse(emit(m)) == m."""
    lines = [
        f"CCSDS_OEM_VERS = {message.version}",
        f"CREATION_DATE = {_format_time(message.creation_date)}",
        f"ORIGINATOR = {message.originator}",
        "",
        "META_START",
        *_metadata_lines(message.metadata),
        "META_STOP",
        "",
        *(_format_state(state) for state in message.states),
    ]
    return "\n".join(lines) + "\n"


# --- admission -----------------------------------------------------------------

def _catalog_number(object_id: str, norad_id: int | None) -> int:
    """OBJECT_ID is free text (the standard recommends the international
    designator). A numeric OBJECT_ID is taken as the catalog number; a caller's
    number must agree with it; otherwise the caller must supply one."""
    stated = int(object_id) if _INTEGER.match(object_id.strip()) else None
    if norad_id is None and stated is None:
        raise EphemerisRejected("NORAD_ID_UNKNOWN", f"OBJECT_ID = {object_id!r}; supply the catalog number")
    if norad_id is not None and stated is not None and norad_id != stated:
        raise EphemerisRejected("NORAD_ID_MISMATCH", f"OBJECT_ID = {object_id!r} but caller says {norad_id}")
    return norad_id if norad_id is not None else stated


def _completeness(message: OemMessage) -> tuple[EphemerisWarning, ...]:
    without_velocity = sum(state.velocity_km_s is None for state in message.states)
    if not without_velocity:
        return ()
    return (
        EphemerisWarning(
            "VELOCITY_ABSENT",
            f"{without_velocity} of {len(message.states)} states carry no velocity, which the "
            "standard requires; positions are interpolated on their own",
        ),
    )


def admit(message: OemMessage, norad_id: int | None = None) -> Admission:
    """Admit a parsed OEM as a StateTable, or raise EphemerisRejected."""
    meta = message.metadata
    if meta.center_name.strip().upper() != "EARTH":
        raise EphemerisRejected("CENTER_NOT_EARTH", f"CENTER_NAME = {meta.center_name!r}")
    require_earth_fixed(meta.ref_frame)
    require_utc(meta.time_system)
    table = StateTable(
        norad_id=_catalog_number(meta.object_id, norad_id),
        name=meta.object_name,
        epochs=tuple(state.epoch for state in message.states),
        positions_km=np.array([state.position_km for state in message.states], dtype=float).reshape(-1, 3),
        created=message.creation_date,
    )
    warnings = _completeness(message)
    for warning in warnings:
        log.warning("Ephemeris admitted incomplete", code=warning.code, object_id=meta.object_id, detail=warning.detail)
    return Admission(table, warnings)
