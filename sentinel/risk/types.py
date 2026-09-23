"""Types for the risk engine.

`Conjunction` is the in-memory projection of a CCSDS 508.0-B-1 Conjunction
Data Message (ADR-001). Parsing CDM wire formats is the ingest module's job;
this module only consumes the parsed result, so the engine has exactly one
input shape regardless of whether the data came from Space-Track, Privateer's
Wayfinder API, or a derived element-set screening.

Unit convention, applied at the boundary and never mixed thereafter:

    positions    kilometres          (as carried in a CDM state vector)
    velocities   kilometres/second   (as carried in a CDM state vector)
    covariance   metres squared      (as carried in a CDM covariance block)
    radii        metres

The engine converts positions and velocities to metres on entry and works
in metres throughout. Every field name below carries its unit as a suffix,
which is a deviation from the design document's shorthand and is deliberate:
unit confusion is the most likely source of a wrong answer in this module.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
from typing import Any

import numpy as np


class Method(enum.Enum):
    """How a result was produced. Always travels with the probability."""

    FOSTER_ESTES_2D = "FOSTER_ESTES_2D"
    REFUSED = "REFUSED"


class RefusalReason(enum.Enum):
    """Why the linear encounter model was not applied.

    A refusal is a result, not an error. The engine declines to produce a
    number the model does not support rather than returning one that looks
    authoritative and is not.
    """

    NO_COVARIANCE = "NO_COVARIANCE"
    NO_HBR = "NO_HBR"
    INVALID_COVARIANCE = "INVALID_COVARIANCE"
    ILL_CONDITIONED_COVARIANCE = "ILL_CONDITIONED_COVARIANCE"
    LOW_RELATIVE_VELOCITY = "LOW_RELATIVE_VELOCITY"
    TCA_INCONSISTENT = "TCA_INCONSISTENT"


@dataclasses.dataclass(frozen=True, eq=False)
class ObjectState:
    """One object's state and uncertainty at time of closest approach."""

    object_id: str
    position_km: np.ndarray
    velocity_km_s: np.ndarray
    covariance_rtn_m2: np.ndarray | None
    radius_m: float | None

    def replace(self, **changes: Any) -> "ObjectState":
        return dataclasses.replace(self, **changes)


@dataclasses.dataclass(frozen=True, eq=False)
class Conjunction:
    """A single close approach between two objects."""

    primary: ObjectState
    secondary: ObjectState
    tca: Any = None

    def replace(self, **changes: Any) -> "Conjunction":
        return dataclasses.replace(self, **changes)

    def inputs_hash(self) -> str:
        """Stable digest of everything the assessment depends on.

        Design principle 2: every risk number must be traceable to the exact
        inputs that produced it. Recomputing this digest later and getting a
        different value means the inputs changed, not that the engine drifted.
        """

        def encode(state: ObjectState) -> dict:
            cov = state.covariance_rtn_m2
            return {
                "id": state.object_id,
                "r": np.asarray(state.position_km, float).tolist(),
                "v": np.asarray(state.velocity_km_s, float).tolist(),
                "c": None if cov is None else np.asarray(cov, float).tolist(),
                "radius": state.radius_m,
            }

        payload = json.dumps(
            {"primary": encode(self.primary), "secondary": encode(self.secondary)},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True)
class AssessmentConfig:
    """Applicability thresholds.

    These are configuration rather than constants because the right value
    depends on the operator's regime - a GEO operator and a LEO operator do
    not agree on what counts as a low relative velocity. Every refusal
    records both the observed value and the threshold it crossed.
    """

    min_relative_speed_m_s: float = 100.0
    tca_residual_abs_m: float = 1.0
    tca_residual_rel: float = 0.01
    max_condition_number: float = 1e12
    default_radius_m: float | None = None
    quadrature_panels_cap: int = 4096


@dataclasses.dataclass(frozen=True)
class AssessedConjunction:
    """The engine's output.

    `pc` is None whenever `method` is REFUSED. `pc` and `method` always
    travel together, so a consumer cannot obtain a probability without also
    obtaining how it was produced.
    """

    method: Method
    pc: float | None
    pc_max: float | None
    dilution_flag: bool
    dilution_margin: float | None
    miss_distance_m: float
    relative_speed_m_s: float
    hbr_m: float | None
    inputs_hash: str
    refusal_reason: RefusalReason | None = None
    diagnostics: dict = dataclasses.field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-serialisable form, for the decision log."""

        def clean(value):
            if isinstance(value, np.ndarray):
                return value.tolist()
            if isinstance(value, (np.floating, np.integer)):
                return value.item()
            if isinstance(value, (enum.Enum,)):
                return value.value
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [clean(v) for v in value]
            return value

        return {
            "method": self.method.value,
            "pc": self.pc,
            "pc_max": self.pc_max,
            "dilution_flag": self.dilution_flag,
            "dilution_margin": self.dilution_margin,
            "miss_distance_m": self.miss_distance_m,
            "relative_speed_m_s": self.relative_speed_m_s,
            "hbr_m": self.hbr_m,
            "inputs_hash": self.inputs_hash,
            "refusal_reason": None if self.refusal_reason is None else self.refusal_reason.value,
            "diagnostics": clean(self.diagnostics),
        }
