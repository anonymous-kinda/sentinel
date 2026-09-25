"""Admission policy for CDMs: what makes a message wrong vs incomplete.

The rule, carried over from how the author runs compliance automation in
production: *wrong raises, incomplete degrades, and both are recorded.*

Wrong (CdmRejected - the message is quarantined with a reason):
  input that would make the engine's answer silently incorrect. A state in
  metres labelled as kilometres, a non-inertial frame treated as inertial,
  three covariance terms out of six, a header miss distance that disagrees
  with the states it summarises, a state or covariance no Earth-orbiting
  object can have, a TCA before there were satellites, or a number the node
  reads or displays that is not a finite number.

Incomplete (a CdmWarning - the message is accepted):
  input that limits what can be concluded, without corrupting it. No
  covariance at all (the engine will refuse a Pc, correctly), or a unit
  label on a non-load-bearing summary field that disagrees with the
  standard. NASA CARA's own AlfanoTestCase CDMs label RELATIVE_VELOCITY_*
  as [m]; that is an anomaly worth recording, not a reason to discard the
  message, because Sentinel recomputes relative velocity from the states.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math

import numpy as np

from .model import (
    POSITION_COVARIANCE_KEYS,
    STATE_POSITION_KEYS,
    STATE_VELOCITY_KEYS,
    CdmMessage,
    CdmSection,
)
from .timefmt import parse_ccsds_time

# Inertial frames accepted without conversion. GCRF and EME2000 differ by a
# frame bias of ~20 milliarcseconds - about 0.7 m at GEO radius, well inside
# any covariance a CDM carries - so both are treated as the same frame.
# ITRF requires Earth-orientation data to convert and is refused rather
# than approximated.
INERTIAL_FRAMES = frozenset({"EME2000", "GCRF"})

# Load-bearing units. An absent label is accepted (the standard's default);
# a present label must match.
_POSITION_UNIT = "km"
_VELOCITY_UNIT = "km/s"
_COVARIANCE_UNIT = "m**2"

# Summary fields: checked, but only warned on.
_SUMMARY_UNITS = {
    "MISS_DISTANCE": "m",
    "RELATIVE_SPEED": "m/s",
    "RELATIVE_POSITION_R": "m",
    "RELATIVE_POSITION_T": "m",
    "RELATIVE_POSITION_N": "m",
    "RELATIVE_VELOCITY_R": "m/s",
    "RELATIVE_VELOCITY_T": "m/s",
    "RELATIVE_VELOCITY_N": "m/s",
}

# The header MISS_DISTANCE is rounded (operational CDMs carry whole metres)
# and describes the true closest approach, while the states sit at a TCA
# rounded to the millisecond. The two therefore differ by up to ~1 m in
# practice; a disagreement beyond this means one of them is wrong.
MISS_DISTANCE_TOLERANCE_ABS_M = 2.0
MISS_DISTANCE_TOLERANCE_REL = 0.005

# No conjunction precedes the first artificial satellite (Sputnik 1,
# launched 1957-10-04). CARA's own sample cases sit at J2000.
EARLIEST_TCA = dt.datetime(1957, 10, 4, tzinfo=dt.UTC)

# A CDM screens objects in orbit about the Earth. These bounds on what such
# an object can be are set from physics, generously; docs/icd/cdm-profile.md
# ("Physical bounds") gives the reasoning.
# The closest the surface comes to the centre: inside it is underground.
WGS84_POLAR_RADIUS_KM = 6356.752314245
# Twice the distance to the Sun-Earth L1 and L2 points (1.5 million km):
# spacecraft on halo and Lissajous orbits there, up to about 1.8 million km
# out, are admitted, while a low-orbit position written in metres (6.4
# million 'km' and up) is still caught.
MAX_RADIUS_KM = 3.0e6
# Above anything bound to the Sun passing the Earth (~73 km/s), far below c.
MAX_SPEED_KM_S = 100.0
# A coordinate confined to +/-R has a variance of at most R**2 (Popoviciu).
MAX_POSITION_VARIANCE_M2 = (MAX_RADIUS_KM * 1000.0) ** 2
# Below this sine of the angle between r and v, the orbital plane is undefined
# to double precision.
MIN_SINE_R_V = 1e-12


class CdmRejected(ValueError):
    """The message would produce a wrong answer. Quarantine it."""

    def __init__(self, code: str, detail: str, object_index: int | None = None):
        self.code = code
        self.detail = detail
        self.object_index = object_index
        where = "" if object_index is None else f" (OBJECT{object_index + 1})"
        super().__init__(f"{code}{where}: {detail}")


@dataclasses.dataclass(frozen=True)
class CdmWarning:
    code: str
    detail: str
    key: str | None = None
    object_index: int | None = None


def _check_unit(section: CdmSection, key: str, expected: str, index: int) -> None:
    field = section.get(key)
    if field is not None and field.unit is not None and field.unit != expected:
        raise CdmRejected(
            "WRONG_UNIT",
            f"{key} is labelled [{field.unit}]; the engine requires [{expected}]",
            index,
        )


def _number(section: CdmSection, key: str, index: int | None = None) -> float | None:
    try:
        return section.number(key)
    except ValueError as exc:
        raise CdmRejected("UNREADABLE", f"{key} is not a number", index) from exc


def _state_vector(section: CdmSection, index: int) -> tuple[np.ndarray, np.ndarray]:
    values = []
    for key in (*STATE_POSITION_KEYS, *STATE_VELOCITY_KEYS):
        value = _number(section, key, index)
        if value is None:
            raise CdmRejected("MISSING_STATE", f"{key} is absent", index)
        if not math.isfinite(value):
            raise CdmRejected("NONFINITE_STATE", f"{key} = {value}", index)
        values.append(value)
    return np.array(values[:3]), np.array(values[3:])


def _check_plausible_state(position_km: np.ndarray, velocity_km_s: np.ndarray, index: int) -> None:
    """Raise for a state no Earth-orbiting object can have. hypot scales
    before it squares, so even a state near the float limit is judged
    without overflowing; past it, the magnitude is inf and fails the bound."""
    radius_km = math.hypot(*position_km)
    if not WGS84_POLAR_RADIUS_KM <= radius_km <= MAX_RADIUS_KM:
        raise CdmRejected(
            "IMPLAUSIBLE_STATE",
            f"|r| = {radius_km:.6g} km is not between the Earth's surface "
            f"({WGS84_POLAR_RADIUS_KM:g} km) and the admitted radius ({MAX_RADIUS_KM:g} km)",
            index,
        )
    speed_km_s = math.hypot(*velocity_km_s)
    if speed_km_s > MAX_SPEED_KM_S:
        raise CdmRejected("IMPLAUSIBLE_STATE", f"|v| = {speed_km_s:.6g} km/s exceeds {MAX_SPEED_KM_S:g} km/s", index)
    # An orbit has angular momentum. With r x v = 0 (no velocity, or velocity
    # along the position) the RTN frame the covariance is written in does not
    # exist. The magnitudes are bounded above, so the cross product is finite.
    if speed_km_s == 0.0 or _sine_of_angle(position_km, velocity_km_s) < MIN_SINE_R_V:
        raise CdmRejected(
            "IMPLAUSIBLE_STATE",
            "position and velocity are parallel or the velocity is zero: no orbital plane, so no RTN frame",
            index,
        )


def _sine_of_angle(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(np.cross(a, b)) / (np.linalg.norm(a) * np.linalg.norm(b)))


def _check_plausible_covariance(section: CdmSection, index: int) -> None:
    """Raise for a position covariance no object inside the admitted radius can have."""
    for key in POSITION_COVARIANCE_KEYS:
        value = _number(section, key, index)
        if value is not None and abs(value) > MAX_POSITION_VARIANCE_M2:
            raise CdmRejected(
                "IMPLAUSIBLE_STATE",
                f"|{key}| = {abs(value):.6g} m**2 exceeds the admitted radius squared, {MAX_POSITION_VARIANCE_M2:.3g} m**2",
                index,
            )


def _read_time(message: CdmMessage, key: str) -> None:
    """Raises ValueError for a time that is not CCSDS, or that no conjunction can have."""
    text = message.preamble.text(key)
    if text is not None and parse_ccsds_time(text) < EARLIEST_TCA:
        raise ValueError(f"{key} {text} precedes the first artificial satellite")


def _check_originator_pc(message: CdmMessage) -> None:
    """The originator's Pc is served beside Sentinel's: it must be a finite number."""
    pc = _number(message.preamble, "COLLISION_PROBABILITY")
    if pc is not None and not math.isfinite(pc):
        raise CdmRejected("UNREADABLE", f"COLLISION_PROBABILITY = {pc} is not a finite number")


def covariance_status(section: CdmSection, index: int) -> str:
    """'present', 'absent', or raises for a partial covariance."""
    finite = []
    for key in POSITION_COVARIANCE_KEYS:
        value = _number(section, key, index)
        finite.append(value is not None and math.isfinite(value))
    if all(finite):
        return "present"
    if not any(finite):
        return "absent"
    missing = [k for k, ok in zip(POSITION_COVARIANCE_KEYS, finite) if not ok]
    raise CdmRejected(
        "PARTIAL_COVARIANCE",
        f"position covariance is missing {', '.join(missing)}; "
        "a partial covariance cannot be completed without inventing data",
        index,
    )


def validate(message: CdmMessage) -> list[CdmWarning]:
    """Raise CdmRejected if the message is wrong; return warnings otherwise."""
    warnings: list[CdmWarning] = []

    # --- header / relative metadata --------------------------------------
    if message.preamble.text("TCA") is None:
        raise CdmRejected("MISSING_TCA", "TCA is absent")
    try:
        _read_time(message, "TCA")
    except ValueError as exc:
        raise CdmRejected("BAD_TCA", str(exc)) from exc
    try:
        _read_time(message, "CREATION_DATE")
    except ValueError as exc:
        raise CdmRejected("BAD_CREATION_DATE", str(exc)) from exc
    _check_originator_pc(message)

    for key, expected in _SUMMARY_UNITS.items():
        field = message.preamble.get(key)
        if field is not None and field.unit is not None and field.unit != expected:
            warnings.append(
                CdmWarning(
                    "UNIT_LABEL_ANOMALY",
                    f"{key} labelled [{field.unit}], standard is [{expected}]; "
                    "summary field only - Sentinel recomputes it from the states",
                    key=key,
                )
            )

    # --- each object -------------------------------------------------------
    states = []
    for index, obj in enumerate(message.objects):
        frame = obj.text("REF_FRAME")
        if frame is None:
            raise CdmRejected("MISSING_REF_FRAME", "REF_FRAME is absent", index)
        if frame not in INERTIAL_FRAMES:
            raise CdmRejected(
                "UNSUPPORTED_REF_FRAME",
                f"REF_FRAME = {frame}; supported inertial frames are "
                f"{', '.join(sorted(INERTIAL_FRAMES))}",
                index,
            )
        for key in STATE_POSITION_KEYS:
            _check_unit(obj, key, _POSITION_UNIT, index)
        for key in STATE_VELOCITY_KEYS:
            _check_unit(obj, key, _VELOCITY_UNIT, index)
        for key in POSITION_COVARIANCE_KEYS:
            _check_unit(obj, key, _COVARIANCE_UNIT, index)

        position_km, velocity_km_s = _state_vector(obj, index)
        _check_plausible_state(position_km, velocity_km_s, index)
        states.append((position_km, velocity_km_s))
        if covariance_status(obj, index) == "present":
            _check_plausible_covariance(obj, index)
        else:
            warnings.append(
                CdmWarning(
                    "COVARIANCE_ABSENT",
                    "no position covariance; geometry only, no Pc will be computed",
                    object_index=index,
                )
            )

    # --- cross-check: the header must describe these states --------------
    header_miss = _number(message.preamble, "MISS_DISTANCE")
    if header_miss is not None and math.isfinite(header_miss):
        (r1, _), (r2, _) = states
        state_miss = float(np.linalg.norm((r2 - r1) * 1000.0))
        tolerance = max(MISS_DISTANCE_TOLERANCE_ABS_M, MISS_DISTANCE_TOLERANCE_REL * state_miss)
        if abs(state_miss - header_miss) > tolerance:
            raise CdmRejected(
                "MISS_DISTANCE_MISMATCH",
                f"header MISS_DISTANCE {header_miss:.3f} m disagrees with the "
                f"states ({state_miss:.3f} m) by more than {tolerance:.3f} m",
            )

    return warnings
