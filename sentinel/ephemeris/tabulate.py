"""Sample a Skyfield satellite into a StateTable of Earth-fixed positions.

The result is DERIVED data: an element set propagated by SGP4 and written
out as a table, for tests, fixtures, or an edge node that wants a table
instead of a propagator. `created` is the element set's epoch, because the
table knows nothing the element set did not.
"""

from __future__ import annotations

import datetime as dt

from skyfield.framelib import itrs
from skyfield.sgp4lib import EarthSatellite
from skyfield.timelib import Timescale

from .table import StateTable


def tabulate(
    satellite: EarthSatellite, ts: Timescale, start: dt.datetime, stop: dt.datetime, step_s: float = 60.0
) -> StateTable:
    count = int((stop - start).total_seconds() // step_s) + 1
    epochs = tuple(start + dt.timedelta(seconds=i * step_s) for i in range(count))
    positions = satellite.at(ts.from_datetimes(epochs)).frame_xyz(itrs).km.T
    return StateTable(
        norad_id=satellite.model.satnum,
        name=satellite.name,
        epochs=epochs,
        positions_km=positions,
        created=satellite.epoch.utc_datetime(),
    )
