"""The public CelesTrak OMM snapshot the pass tests run on (see fixtures/omm/)."""

import functools
import json
import pathlib

from skyfield.api import EarthSatellite, load

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "fixtures" / "omm" / "celestrak-resource-20260924.json"

# Bundled leap-second and Delta T tables only: no download, no JPL ephemeris.
TIMESCALE = load.timescale(builtin=True)


@functools.cache
def omm_records() -> dict[int, dict]:
    return {record["NORAD_CAT_ID"]: record for record in json.loads(SNAPSHOT.read_text())}


def satellite(norad_id: int) -> EarthSatellite:
    return EarthSatellite.from_omm(TIMESCALE, omm_records()[norad_id])
