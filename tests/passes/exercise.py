"""Exercise inputs shared by the pass-engine tests.

The unit is an exercise position (ORIGINATOR=SENTINEL-EXERCISE), not a
real one. The interval starts just after the snapshot was retrieved.
"""

import datetime as dt
import pathlib

from sentinel.passes.model import Unit

SNAPSHOT = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "omm" / "celestrak-resource-20260924.json"
EXERCISE_UNIT = Unit(unit_id="EXERCISE-NTC", lat_deg=35.26, lon_deg=-116.68)
START = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
END = START + dt.timedelta(hours=24)
