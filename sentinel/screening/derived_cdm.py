"""A screened approach as a DERIVED CCSDS 508.0-B-1 CDM, with no covariance.

ADR-001 makes the CDM the one input shape downstream of ingest, so a
screened approach travels as a CDM like any other. What cannot be
populated honestly is left out rather than filled with plausible values:

- no covariance block, and no COVARIANCE_METHOD (508.0-B-1 makes both
  mandatory; there is nothing true to write in either). The engine's
  existing NO_COVARIANCE gate therefore refuses a Pc - by construction,
  with no screening branch in the engine;
- OBJECT_TYPE UNKNOWN and MANEUVERABLE N/A: GP element sets say neither;
- no RELATIVE_POSITION/VELOCITY_RTN summary (optional; the engine
  recomputes it from the states).

States are the SGP4 positions at the TCA rounded to the millisecond (the
CDM's time resolution), transformed TEME -> GCRF by Skyfield. MISS_DISTANCE
and RELATIVE_SPEED describe those states, so the header can never disagree
with them. Each object block names the element set it came from by the
same sha256 the sync layer uses for that record.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping

import numpy as np

from ..cdm.model import CdmMessage, CdmSection, Comment, KvnField
from ..cdm.timefmt import format_ccsds_time
from ..passes.element_store import canonical_bytes
from .orbit import Orbit
from .screen import CloseApproach, ScreeningResult

ORIGINATOR = "SENTINEL-SCREENING"
DEMONSTRATION_COMMENT = "Demonstration mode: element-set geometry only; no probability of collision (ADR-002)"
REF_FRAME = "GCRF"


def derived_cdms(result: ScreeningResult, elements: Mapping[int, dict], created: dt.datetime) -> list[CdmMessage]:
    """One CDM per approach in the result, in TCA order."""
    return [derived_cdm(result, approach, elements, created) for approach in result.approaches]


def derived_cdm(
    result: ScreeningResult, approach: CloseApproach, elements: Mapping[int, dict], created: dt.datetime
) -> CdmMessage:
    tca = nearest_millisecond(approach.tca)
    orbits = [Orbit.from_omm(elements[approach.primary_id]), Orbit.from_omm(elements[approach.secondary_id])]
    (r1, v1), (r2, v2) = (orbit.gcrf_state_km(tca) for orbit in orbits)
    preamble = CdmSection(
        (
            KvnField("CCSDS_CDM_VERS", "1.0"),
            KvnField("CREATION_DATE", format_ccsds_time(created)),
            KvnField("ORIGINATOR", ORIGINATOR),
            KvnField("MESSAGE_FOR", orbits[0].name),
            KvnField("MESSAGE_ID", f"SCREEN-{approach.primary_id}-{approach.secondary_id}-{tca:%Y%m%dT%H%M%S}"),
            Comment(DEMONSTRATION_COMMENT),
            Comment("DERIVED data: SGP4 on public element sets, kilometre-scale error, no covariance"),
            Comment(f"screened within {result.threshold_km:.3f} km of the primary"),
            KvnField("TCA", format_ccsds_time(tca)),
            KvnField("MISS_DISTANCE", f"{np.linalg.norm(r2 - r1) * 1000.0:.3f}", "m"),
            KvnField("RELATIVE_SPEED", f"{np.linalg.norm(v2 - v1) * 1000.0:.3f}", "m/s"),
            KvnField("START_SCREEN_PERIOD", format_ccsds_time(result.start)),
            KvnField("STOP_SCREEN_PERIOD", format_ccsds_time(result.end)),
        )
    )
    return CdmMessage(
        preamble=preamble,
        objects=(_object(1, orbits[0], r1, v1, tca), _object(2, orbits[1], r2, v2, tca)),
    )


def nearest_millisecond(when: dt.datetime) -> dt.datetime:
    """The CDM's time resolution: the TCA it states, and the instant of its states."""
    milliseconds = round(when.microsecond / 1000.0)
    return when.replace(microsecond=0) + dt.timedelta(milliseconds=milliseconds)


def _object(index: int, orbit: Orbit, r_km: np.ndarray, v_km_s: np.ndarray, tca: dt.datetime) -> CdmSection:
    sha16 = hashlib.sha256(canonical_bytes(orbit.fields)).hexdigest()[:16]
    age_days = (tca - orbit.epoch).total_seconds() / 86400.0
    entries = [
        KvnField("OBJECT", f"OBJECT{index}"),
        KvnField("OBJECT_DESIGNATOR", str(orbit.norad_id)),
        KvnField("CATALOG_NAME", "SATCAT"),
        KvnField("OBJECT_NAME", orbit.name),
        KvnField("INTERNATIONAL_DESIGNATOR", str(orbit.fields.get("OBJECT_ID", "UNKNOWN"))),
        KvnField("OBJECT_TYPE", "UNKNOWN"),
        KvnField("EPHEMERIS_NAME", "NONE"),
        KvnField("MANEUVERABLE", "N/A"),
        KvnField("REF_FRAME", REF_FRAME),
        Comment(
            f"state: SGP4 on element set sha256 {sha16}, epoch {format_ccsds_time(orbit.epoch)} "
            f"(age {age_days:.2f} d at TCA), TEME to GCRF by Skyfield"
        ),
        Comment("no covariance: element sets carry none, so none is written (ADR-002)"),
    ]
    entries += [KvnField(key, f"{value:.6f}", "km") for key, value in zip(("X", "Y", "Z"), r_km)]
    entries += [KvnField(key, f"{value:.9f}", "km/s") for key, value in zip(("X_DOT", "Y_DOT", "Z_DOT"), v_km_s)]
    return CdmSection(tuple(entries))
