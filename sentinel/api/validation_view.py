"""The Validation tab: Sentinel against NASA CARA, computed live on this node.

The same comparison the test suite asserts and the report prints, run by
the deployed engine on the first request for it (GET /api/validation),
then cached for the life of the process. If a node was built with a
different engine than the one validated, its own Validation tab shows it.
"""

from __future__ import annotations

import math

from ..risk.engine import assess
from ..risk.types import Method


class ValidationView:
    def __init__(self) -> None:
        self._cache: dict | None = None

    def summary(self) -> dict:
        if self._cache is None:
            self._cache = self._compute()
        return self._cache

    def _compute(self) -> dict:
        try:
            from ..validation.cara import load_cases
        except ImportError:  # pragma: no cover
            return {"available": False}
        cases = load_cases()
        operational = [c for c in cases if c.group == "cara_operational"]
        if not operational:
            return {"available": False, "reason": "NASA CARA fixtures not bundled with this node"}

        rows = []
        confusion = {"tp": 0, "fn": 0, "fp": 0, "tn": 0}
        errors = []
        for c in operational:
            conj = c.conjunction()
            forced = assess(conj, c.override_config())
            default = assess(conj)
            expected = c.expected["pc2d"]
            rel = abs(forced.pc - expected) / expected
            errors.append(rel)
            flagged = c.expected["cara_pc2d_usage_violation"]
            refused = default.method is Method.REFUSED
            key = {(True, True): "tp", (False, True): "fn", (True, False): "fp", (False, False): "tn"}[
                (refused, flagged)
            ]
            confusion[key] += 1
            rows.append(
                {
                    "case_id": c.case_id,
                    "primary": c.expected["primary"],
                    "secondary": c.expected["secondary"],
                    "sentinel_pc": forced.pc,
                    "cara_pc2d": expected,
                    "cara_nc3d": c.expected["nc3d"],
                    "rel_error": rel,
                    "cara_says_2d_valid": not flagged,
                    "sentinel_default": default.method.value,
                    "refusal_reason": None if default.refusal_reason is None else default.refusal_reason.value,
                    "relative_speed_m_s": default.relative_speed_m_s,
                }
            )
        alfano = []
        for c in [c for c in cases if c.group == "alfano_2009"]:
            forced = assess(c.conjunction(), c.override_config())
            alfano.append(
                {
                    "case_id": c.case_id,
                    "sentinel_pc": forced.pc,
                    "cara_pc2d": c.expected["pc2d"],
                    "rel_error": abs(forced.pc - c.expected["pc2d"]) / c.expected["pc2d"],
                }
            )
        errors.sort()
        return {
            "available": True,
            "source": "NASA CARA Analysis Tools, commit 1c78beb (vendored unmodified)",
            "operational_count": len(operational),
            "worst_rel_error": max(errors),
            "median_rel_error": errors[len(errors) // 2],
            "confusion": confusion,
            "rows": rows,
            "alfano": alfano,
            "alfano_worst_rel_error": max((a["rel_error"] for a in alfano), default=math.nan),
            "calibration_note": "The curvilinear threshold (0.1) was calibrated on these 53 "
            "events; agreement is in-sample.",
        }
