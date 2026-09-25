"""The dilution curve is drawn by the engine the node is configured with.

`dilution_curve` used the integrator's default panel cap, not the
engine configuration's `quadrature_panels_cap`, so the curve agreed with
the assessment beside it only under the default configuration.
"""

import asyncio
import datetime as dt

import numpy as np

from sentinel.bus import InProcessBus
from sentinel.cdm import admit
from sentinel.clock import FixedClock
from sentinel.conjunction.service import ConjunctionService
from sentinel.conjunction.store import ConjunctionStore
from sentinel.risk.encounter import build_encounter_plane, pc_curve
from sentinel.risk.types import AssessmentConfig

from ..test_cdm_codec import OPERATIONAL

NOW = dt.datetime(2026, 9, 23, 12, tzinfo=dt.UTC)
# Below the uniform rule's panel count for this CDM (2.5 at k = 1, more at
# the smaller scales the k* search and the curve visit): the windowed rule runs.
CAPPED = AssessmentConfig(quadrature_panels_cap=1)


def assessed(config: AssessmentConfig) -> tuple[ConjunctionService, dict]:
    service = ConjunctionService(ConjunctionStore(":memory:"), InProcessBus(), FixedClock(NOW), engine_config=config)
    asyncio.run(service.ingest(OPERATIONAL.read_bytes(), "test", "REAL"))
    [event] = service.list_events("all")
    return service, event


def headline(assessment: dict) -> tuple[float, float, float]:
    return assessment["pc"], assessment["pc_max"], assessment["diagnostics"]["k_star"]


def curve_at(log10_k: list[float], panel_cap: int) -> list[float]:
    conjunction = admit(OPERATIONAL.read_bytes()).conversion.conjunction
    plane = build_encounter_plane(conjunction, conjunction.primary.radius_m + conjunction.secondary.radius_m)
    return pc_curve(plane, np.array(log10_k), panel_cap=panel_cap).tolist()


def test_the_cap_moves_these_numbers_so_the_check_below_can_fail():
    _, default = assessed(AssessmentConfig())
    service, capped = assessed(CAPPED)
    assert capped["assessment"]["method"] == "FOSTER_ESTES_2D"
    assert headline(capped["assessment"]) != headline(default["assessment"])
    grid = service.dilution_curve(capped["event_id"])["log10_k"]
    assert curve_at(grid, CAPPED.quadrature_panels_cap) != curve_at(grid, AssessmentConfig().quadrature_panels_cap)


def test_the_curve_is_drawn_with_the_configured_panel_cap():
    service, event = assessed(CAPPED)
    curve = service.dilution_curve(event["event_id"])
    assert (curve["pc_at_k1"], curve["pc_max"], curve["k_star"]) == headline(event["assessment"])
    assert curve["pc"] == curve_at(curve["log10_k"], CAPPED.quadrature_panels_cap)
