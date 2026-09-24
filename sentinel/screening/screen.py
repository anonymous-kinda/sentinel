"""Screen one primary against a set of public element sets (ADR-002 demonstration mode).

Geometry only: when, how close, how fast. No probability of collision is
computed here or anywhere downstream of an element set - there is no
covariance to compute one from.

Ingest rule, applied per object: a primary that cannot be propagated
refuses the whole screening (every answer would be wrong); a secondary
that cannot be propagated is skipped, named in the result with its
reason, and the rest are still screened (the answer is incomplete, and
says so).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import time
from collections.abc import Mapping

from ..obs import get_logger
from .orbit import Orbit, OrbitUnusable
from .prefilter import may_approach
from .search import (
    DEFAULT_STEP_S,
    RelativeState,
    find_close_approaches,
    require_positive,
    sample_times,
)

log = get_logger(__name__)

DEFAULT_THRESHOLD_KM = 5.0
DEFAULT_HOURS = 24.0


class ScreeningRefused(ValueError):
    """The screening as asked cannot give a right answer. `code` names why."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclasses.dataclass(frozen=True)
class CloseApproach:
    primary_id: int
    secondary_id: int
    secondary_name: str
    tca: dt.datetime
    miss_distance_km: float
    relative_speed_km_s: float


@dataclasses.dataclass(frozen=True)
class SkippedObject:
    norad_id: int
    code: str
    detail: str


@dataclasses.dataclass(frozen=True)
class ScreeningResult:
    primary_id: int
    primary_name: str
    start: dt.datetime
    end: dt.datetime
    threshold_km: float
    secondaries: int            # objects screened against the primary
    after_prefilter: int        # of those, how many were propagated
    approaches: tuple[CloseApproach, ...]
    skipped: tuple[SkippedObject, ...]
    runtime_s: float


def screen(
    primary_id: int,
    elements: Mapping[int, dict],
    start: dt.datetime,
    hours: float = DEFAULT_HOURS,
    threshold_km: float = DEFAULT_THRESHOLD_KM,
    step_s: float = DEFAULT_STEP_S,
) -> ScreeningResult:
    """Every approach of any object to the primary within threshold_km, in TCA order."""
    require_positive(hours=hours, threshold_km=threshold_km, step_s=step_s)
    if start.tzinfo is None:
        raise ValueError("refusing a naive datetime; screening times are UTC")
    started = time.perf_counter()
    duration_s = hours * 3600.0
    primary = _primary(primary_id, elements, start, duration_s, step_s)

    approaches: list[CloseApproach] = []
    skipped: list[SkippedObject] = []
    after_prefilter = 0
    for norad_id, fields in elements.items():
        if norad_id == primary_id:
            continue
        try:
            secondary = Orbit.from_omm(fields)
            if not may_approach(primary.radial_band_km, secondary.radial_band_km, threshold_km):
                continue
            after_prefilter += 1
            approaches.extend(_pair_approaches(primary, secondary, start, duration_s, threshold_km, step_s))
        except OrbitUnusable as exc:
            if exc.norad_id == primary_id:
                raise ScreeningRefused(exc.code, f"primary {primary_id}: {exc.detail}") from exc
            log.warning("Element set skipped", norad_id=norad_id, code=exc.code, detail=exc.detail)
            skipped.append(SkippedObject(norad_id, exc.code, exc.detail))

    result = ScreeningResult(
        primary_id=primary_id,
        primary_name=primary.name,
        start=start,
        end=start + dt.timedelta(seconds=duration_s),
        threshold_km=threshold_km,
        secondaries=len(elements) - 1,
        after_prefilter=after_prefilter,
        approaches=tuple(sorted(approaches, key=lambda a: a.tca)),
        skipped=tuple(skipped),
        runtime_s=time.perf_counter() - started,
    )
    log.info(
        "Screening complete",
        primary_id=primary_id,
        secondaries=result.secondaries,
        after_prefilter=after_prefilter,
        approaches=len(result.approaches),
        skipped=len(skipped),
        runtime_s=round(result.runtime_s, 3),
    )
    return result


def _primary(primary_id: int, elements: Mapping[int, dict], start: dt.datetime, duration_s: float, step_s: float) -> Orbit:
    """The primary's orbit, propagated across the whole window once, or a refusal."""
    if primary_id not in elements:
        raise ScreeningRefused("UNKNOWN_PRIMARY", f"no element set for NORAD {primary_id}")
    try:
        primary = Orbit.from_omm(elements[primary_id])
        primary.teme_km(start, sample_times(duration_s, step_s))
    except OrbitUnusable as exc:
        raise ScreeningRefused(exc.code, f"primary {primary_id}: {exc.detail}") from exc
    return primary


def _relative_motion(primary: Orbit, secondary: Orbit, start: dt.datetime) -> RelativeState:
    def relative_state(t_s):
        r1, v1 = primary.teme_km(start, t_s)
        r2, v2 = secondary.teme_km(start, t_s)
        return r2 - r1, v2 - v1

    return relative_state


def _pair_approaches(
    primary: Orbit, secondary: Orbit, start: dt.datetime, duration_s: float, threshold_km: float, step_s: float
) -> list[CloseApproach]:
    minima = find_close_approaches(_relative_motion(primary, secondary, start), duration_s, threshold_km, step_s)
    return [
        CloseApproach(
            primary_id=primary.norad_id,
            secondary_id=secondary.norad_id,
            secondary_name=secondary.name,
            tca=start + dt.timedelta(seconds=m.t_s),
            miss_distance_km=m.miss_distance_km,
            relative_speed_km_s=m.relative_speed_km_s,
        )
        for m in minima
    ]
