"""CDM -> risk.Conjunction.

This is the one place that knows both vocabularies. The risk engine stays
ignorant of CDMs (ADR-001): it consumes a Conjunction whatever its source.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from ..risk.types import Conjunction, ObjectState
from .model import POSITION_COVARIANCE_KEYS, CdmMessage, CdmSection
from .validate import CdmWarning, _number, covariance_status, validate


@dataclasses.dataclass(frozen=True)
class Conversion:
    """The Conjunction plus everything needed to explain how it was built."""

    conjunction: Conjunction
    hbr_source: str | None
    warnings: tuple[CdmWarning, ...]


def _covariance_rtn_m2(section: CdmSection, index: int) -> np.ndarray | None:
    if covariance_status(section, index) == "absent":
        return None
    cr_r, ct_r, ct_t, cn_r, cn_t, cn_n = (section.number(k) for k in POSITION_COVARIANCE_KEYS)
    return np.array(
        [
            [cr_r, ct_r, cn_r],
            [ct_r, ct_t, cn_t],
            [cn_r, cn_t, cn_n],
        ],
        dtype=float,
    )


def _radius_from_area_m(section: CdmSection, index: int) -> float | None:
    area = _number(section, "AREA_PC", index)
    if area is None or not math.isfinite(area) or area <= 0.0:
        return None
    return math.sqrt(area / math.pi)


def resolve_radii(
    message: CdmMessage, hbr_override_m: float | None = None
) -> tuple[tuple[float | None, float | None], str | None]:
    """Per-object radii and where they came from.

    Precedence: an explicit override, then a combined HBR in a COMMENT line
    (CARA's convention, split evenly between the objects since only the sum
    enters the 2D integral), then each object's AREA_PC. If none is
    available the radii are None and the engine refuses with NO_HBR unless
    its configuration supplies a default - no radius is ever invented here.
    """
    if hbr_override_m is not None:
        return (hbr_override_m / 2.0, hbr_override_m / 2.0), "override"
    combined = message.hbr_from_comment_m()
    if combined is not None:
        return (combined / 2.0, combined / 2.0), "cdm_comment_hbr"
    r1 = _radius_from_area_m(message.objects[0], 0)
    r2 = _radius_from_area_m(message.objects[1], 1)
    if r1 is not None and r2 is not None:
        return (r1, r2), "area_pc"
    return (None, None), None


def to_conjunction(message: CdmMessage, hbr_override_m: float | None = None) -> Conversion:
    """Validate and convert. Raises CdmRejected if the message is wrong."""
    warnings = validate(message)
    (radius1, radius2), hbr_source = resolve_radii(message, hbr_override_m)

    states = []
    for index, (section, radius) in enumerate(zip(message.objects, (radius1, radius2))):
        states.append(
            ObjectState(
                object_id=section.text("OBJECT_DESIGNATOR") or f"OBJECT{index + 1}",
                position_km=np.array([section.number(k) for k in ("X", "Y", "Z")], float),
                velocity_km_s=np.array(
                    [section.number(k) for k in ("X_DOT", "Y_DOT", "Z_DOT")], float
                ),
                covariance_rtn_m2=_covariance_rtn_m2(section, index),
                radius_m=radius,
            )
        )

    return Conversion(
        conjunction=Conjunction(primary=states[0], secondary=states[1], tca=message.tca),
        hbr_source=hbr_source,
        warnings=tuple(warnings),
    )
