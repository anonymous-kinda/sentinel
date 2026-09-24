"""A screening result as text: what was screened, what was found, what it is not.

Every approach line carries the refusal next to the numbers, because a
caveat in a README does not appear next to the number on the screen
(ADR-002). No probability of collision is printed, ever.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping

from ..cdm.timefmt import format_ccsds_time
from ..passes.element_store import element_epoch
from .derived_cdm import nearest_millisecond
from .screen import CloseApproach, ScreeningResult

BANNER = "DEMONSTRATION MODE - element-set geometry only, DERIVED data, no probability of collision (ADR-002)"
PC_REFUSED = "Pc: refused — element sets have no covariance"


def report_lines(result: ScreeningResult, elements: Mapping[int, dict]) -> list[str]:
    hours = (result.end - result.start).total_seconds() / 3600.0
    lines = [
        BANNER,
        f"primary   {result.primary_id} {result.primary_name}, "
        f"element set epoch {_utc(element_epoch(elements[result.primary_id]))}",
        f"window    {_utc(result.start)} to {_utc(result.end)} ({hours:g} h), threshold {result.threshold_km:.3f} km",
        f"screened  {result.secondaries} objects: {result.after_prefilter} past the apogee/perigee filter, "
        f"{len(result.skipped)} skipped, {result.runtime_s:.2f} s",
        *(f"skipped   {s.norad_id} {s.code}: {s.detail}" for s in result.skipped),
        "",
    ]
    if not result.approaches:
        return [*lines, f"no close approaches within {result.threshold_km:.3f} km"]
    header = f"{'OBJECT':<32} {'TCA (UTC)':<24} {'MISS km':>9} {'REL km/s':>9}"
    return [*lines, header, *(_approach_line(a) for a in result.approaches)]


def _approach_line(approach: CloseApproach) -> str:
    obj = f"{approach.secondary_id} {approach.secondary_name}"
    return (
        f"{obj:<32.32} {_utc(nearest_millisecond(approach.tca)):<24} "
        f"{approach.miss_distance_km:>9.3f} {approach.relative_speed_km_s:>9.3f}  {PC_REFUSED}"
    )


def _utc(when: dt.datetime) -> str:
    return format_ccsds_time(when) + "Z"
