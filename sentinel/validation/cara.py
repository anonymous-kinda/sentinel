"""Load NASA CARA published cases (fixtures/cara_cases.json) as Conjunctions.

Shared by the Tier 3 tests and scripts/validation_report.py, so the report
and the test suite cannot drift apart on how a case is interpreted.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import pathlib
from typing import Any

import numpy as np

from ..cdm import parse_bytes, to_conjunction
from ..risk.frames import rtn_to_eci_matrix
from ..risk.types import AssessmentConfig, Conjunction, ObjectState

REPO = pathlib.Path(__file__).resolve().parents[2]
# In a source checkout the fixtures sit at the repo root; an installed
# bundle ships them separately and points here with SENTINEL_FIXTURES.
FIXTURES = pathlib.Path(os.environ.get("SENTINEL_FIXTURES", REPO / "fixtures"))
CASES_FILE = FIXTURES / "cara_cases.json"
CARA_DIR = FIXTURES / "cara"


@dataclasses.dataclass(frozen=True)
class CaraCase:
    raw: dict[str, Any]

    @property
    def case_id(self) -> str:
        return self.raw["case_id"]

    @property
    def group(self) -> str:
        return self.raw["group"]

    @property
    def expected(self) -> dict[str, Any]:
        return self.raw["expected"]

    @property
    def rtol(self) -> float:
        return float(self.raw["tolerance"]["rtol"])

    def conjunction(self) -> Conjunction:
        inputs = self.raw["inputs"]
        hbr_m = float(self.raw["hbr_m"])
        if "cdm_file" in inputs:
            data = (CARA_DIR / inputs["cdm_file"]).read_bytes()
            return to_conjunction(parse_bytes(data), hbr_override_m=hbr_m).conjunction
        return _inline_conjunction(inputs["inline"], hbr_m)

    def override_config(self) -> AssessmentConfig:
        """Configuration that reproduces CARA's 'compute regardless' setting."""
        override = self.raw.get("config_override") or {}
        fields: dict[str, Any] = {k: (math.inf if v is None else v) for k, v in override.items()}
        return AssessmentConfig(**fields)


def _inline_conjunction(spec: dict[str, Any], hbr_m: float) -> Conjunction:
    """Inline CARA unit-test inputs: ECI, km, km/s, km^2.

    Sentinel takes each covariance in its object's own RTN frame, in m^2,
    so each ECI covariance is rotated into RTN (M^T C M) and scaled by 1e6.
    """
    if spec["frame"] != "ECI" or spec["units"]["covariance"] != "km**2":
        raise ValueError(f"unsupported inline case convention: {spec['frame']} {spec['units']}")

    def state(name: str, r, v, c) -> ObjectState:
        r = np.array(r, float)
        v = np.array(v, float)
        m = rtn_to_eci_matrix(r, v)
        cov_rtn_m2 = m.T @ (np.array(c, float) * 1e6) @ m
        return ObjectState(name, r, v, cov_rtn_m2, hbr_m / 2.0)

    return Conjunction(
        primary=state("PRIMARY", spec["r1"], spec["v1"], spec["c1"]),
        secondary=state("SECONDARY", spec["r2"], spec["v2"], spec["c2"]),
    )


def load_cases() -> list[CaraCase]:
    if not CASES_FILE.exists():
        return []
    return [CaraCase(c) for c in json.loads(CASES_FILE.read_text())["cases"]]


def verify_vendored_files() -> list[str]:
    """Return the vendored files whose sha256 no longer matches SHA256SUMS."""
    bad = []
    for line in (CARA_DIR / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        path = CARA_DIR / name.strip()
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            bad.append(name.strip())
    return bad
