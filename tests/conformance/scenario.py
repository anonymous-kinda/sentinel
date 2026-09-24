"""The exercise every pass provider is held to.

A unit at the National Training Center (35.26 N, 116.68 W), 24 hours from
2026-09-24T06:00Z, and imagers whose fields of regard are planning
assumptions made for this test, not published sensor specifications. The
orbits are the public CelesTrak element sets in fixtures/omm/.
"""

import dataclasses
import datetime as dt

from sentinel.passes.model import Imager, Unit
from tests.omm_snapshot import omm_records

ASSUMED = "conformance-test assumption, not a published specification"


@dataclasses.dataclass(frozen=True)
class Scenario:
    unit: Unit
    start: dt.datetime
    end: dt.datetime
    imagers: tuple[Imager, ...]

    @property
    def omm_records(self) -> tuple[dict, ...]:
        """The public element sets of this scenario's imagers, as a provider factory needs them."""
        records = omm_records()
        return tuple(records[imager.norad_id] for imager in self.imagers)


START = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)

SCENARIO = Scenario(
    unit=Unit("NTC-EXERCISE", 35.26, -116.68),
    start=START,
    end=START + dt.timedelta(hours=24),
    imagers=(
        Imager(40115, "WORLDVIEW-3", "EO", 45.0, basis=ASSUMED),
        Imager(39634, "SENTINEL-1A", "SAR", 45.0, basis=ASSUMED),
        Imager(39084, "LANDSAT 8", "EO", 7.5, basis=ASSUMED),
        # Horizon-limited (the field of regard reaches past the horizon): the
        # mask is 0 deg, where the elevation changes slowest and timing is
        # hardest.
        Imager(40697, "SENTINEL-2A", "EO", 70.0, basis=ASSUMED),
    ),
)

# In no provider's data: it must get no windows.
STRANGER = Imager(99999, "NOT-IN-ANY-DATA", "EO", 45.0, basis=ASSUMED)
