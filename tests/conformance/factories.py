"""Provider factories: build a provider for a Scenario from its public element sets.

A factory takes a Scenario and returns something that satisfies
sentinel.passes.model.PassProvider. To put a new provider under the
conformance suite, write a factory here and add one pytest.param line to
PROVIDER_FACTORIES in test_pass_providers.py.
"""

import datetime as dt

from skyfield.api import EarthSatellite

from sentinel.ephemeris.tabulate import tabulate
from sentinel.passes.providers.tabulated import TabulatedEphemerisProvider
from tests.omm_snapshot import TIMESCALE

from .scenario import Scenario

TABLE_MARGIN = dt.timedelta(hours=1)
TABLE_STEP_S = 60.0


def tabulated_from_skyfield(scenario: Scenario) -> TabulatedEphemerisProvider:
    """ITRF tables sampled from Skyfield SGP4 every 60 s, an hour either side of the day."""
    tables = {}
    for record in scenario.omm_records:
        table = tabulate(
            EarthSatellite.from_omm(TIMESCALE, record),
            TIMESCALE,
            scenario.start - TABLE_MARGIN,
            scenario.end + TABLE_MARGIN,
            step_s=TABLE_STEP_S,
        )
        tables[table.norad_id] = table
    return TabulatedEphemerisProvider(tables)
