"""Element sets: load a public OMM snapshot and pair it with the catalog.

A snapshot is CelesTrak GP data in CCSDS OMM JSON form (a list of flat
records). A record that SGP4 could not use, or two records with the same
NORAD id, make every later answer wrong, so they raise `ElementSetError`.

Pairing is where input becomes *incomplete* rather than wrong. The matcher
skips an imager whose NORAD id has no element set, or whose element set's
OBJECT_NAME is not the catalog name followed by nothing or by a space
("WORLDVIEW-3" matches "WORLDVIEW-3 (WV-3)"; "SKYSAT-C1" does not match
"SKYSAT-C10"). Each skipped imager is logged and returned with its reason,
so a caller can say which imagers were not assessed. None is dropped
silently.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import json
import math
import pathlib
from collections.abc import Iterable, Mapping
from typing import Any

from sentinel.obs import get_logger

from .geometry import EARTH_RADIUS_KM
from .model import Imager

log = get_logger(__name__)

EARTH_GM_KM3_S2 = 398600.4418     # WGS-84
SECONDS_PER_DAY = 86400.0

# The fields sgp4.omm.initialize reads, plus OBJECT_NAME for matching.
REQUIRED_FIELDS = (
    "OBJECT_NAME", "OBJECT_ID", "NORAD_CAT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY",
    "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR",
    "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT", "EPHEMERIS_TYPE", "CLASSIFICATION_TYPE",
    "ELEMENT_SET_NO", "REV_AT_EPOCH",
)

ElementSet = Mapping[str, Any]


class ElementSetError(ValueError):
    """An element set that would make a pass prediction wrong."""


class SkipReason(enum.Enum):
    MISSING = "missing"               # no element set for the NORAD id
    NAME_MISMATCH = "name_mismatch"   # the id's element set is another object


@dataclasses.dataclass(frozen=True)
class Skipped:
    imager: Imager
    reason: SkipReason
    object_name: str | None = None


@dataclasses.dataclass(frozen=True)
class Match:
    imagers: list[Imager]
    element_sets: dict[int, ElementSet]
    skipped: list[Skipped]


def load_omm(path: str | pathlib.Path) -> dict[int, ElementSet]:
    records = json.loads(pathlib.Path(path).read_text())
    if not isinstance(records, list):
        raise ElementSetError(f"{path}: an OMM JSON snapshot is a list of records")
    by_id: dict[int, ElementSet] = {}
    for record in records:
        missing = [field for field in REQUIRED_FIELDS if field not in record]
        if missing:
            raise ElementSetError(f"{path}: {record.get('OBJECT_NAME', '?')!r} is missing {', '.join(missing)}")
        norad_id = int(record["NORAD_CAT_ID"])
        if norad_id in by_id:
            raise ElementSetError(f"{path}: duplicate NORAD_CAT_ID {norad_id}")
        by_id[norad_id] = record
    return by_id


def epoch_utc(element_set: ElementSet) -> dt.datetime:
    """OMM EPOCH is UTC without a zone designator (CCSDS 502.0)."""
    return dt.datetime.fromisoformat(element_set["EPOCH"]).replace(tzinfo=dt.UTC)


def orbital_period_s(element_set: ElementSet) -> float:
    mean_motion = float(element_set["MEAN_MOTION"])       # revolutions per day
    if mean_motion <= 0.0:
        raise ElementSetError(f"MEAN_MOTION {mean_motion} must be positive")
    return SECONDS_PER_DAY / mean_motion


def mean_altitude_km(element_set: ElementSet) -> float:
    """Semi-major axis from mean motion (Kepler's third law), less the
    equatorial radius. Good to a few kilometres for a near-circular orbit,
    which moves a mask elevation by a small fraction of a degree."""
    mean_motion_rad_s = 2.0 * math.pi / orbital_period_s(element_set)
    semi_major_axis_km = (EARTH_GM_KM3_S2 / mean_motion_rad_s**2) ** (1.0 / 3.0)
    return semi_major_axis_km - EARTH_RADIUS_KM


def names_match(catalog_name: str, object_name: str) -> bool:
    return object_name == catalog_name or object_name.startswith(catalog_name + " ")


def skip_reason(imager: Imager, element_sets: Mapping[int, ElementSet]) -> SkipReason | None:
    element_set = element_sets.get(imager.norad_id)
    if element_set is None:
        return SkipReason.MISSING
    if not names_match(imager.name, element_set["OBJECT_NAME"]):
        return SkipReason.NAME_MISMATCH
    return None


def match_catalog(imagers: Iterable[Imager], element_sets: Mapping[int, ElementSet]) -> Match:
    matched: list[Imager] = []
    skipped: list[Skipped] = []
    for imager in imagers:
        reason = skip_reason(imager, element_sets)
        if reason is None:
            matched.append(imager)
            continue
        object_name = element_sets[imager.norad_id]["OBJECT_NAME"] if reason is SkipReason.NAME_MISMATCH else None
        log.warning("Imager skipped", norad_id=imager.norad_id, name=imager.name, reason=reason.value, object_name=object_name)
        skipped.append(Skipped(imager, reason, object_name))
    return Match(
        imagers=matched,
        element_sets={i.norad_id: element_sets[i.norad_id] for i in matched},
        skipped=skipped,
    )
