"""The imaging catalog: which public imagers the pass engine counts.

`imaging.toml` lists high-resolution optical (EO) and radar (SAR) imagers
from the public catalog, each present in the vendored CelesTrak snapshot.

Every `max_off_nadir_deg` is a **planning assumption**, not a measured or
guaranteed capability. Each is taken from a public spec sheet (vendor
datasheet or user guide, ESA Earth Online, eoPortal), rounded, and cited
in the entry's `basis`. Where no public maximum exists, the entry says
so and states the value assumed.

The assumptions err wide, on purpose. A wider field of regard gives a lower
mask elevation and a longer window, so it over-reports observed time and
never under-reports a gap. That is the conservative direction for a unit
asking when no catalogued imager can see it.

SAR entries record the maximum *incidence* angle as the maximum off-nadir
angle. Incidence at the ground always exceeds the look angle at the
satellite (Earth curvature), so this overstates the field of regard. The
same reading ignores two more limits: the near-nadir blind zone (a SAR
cannot image below its minimum incidence) and the look side (most look to
one side only). All three over-report observed time and never
under-report a gap. Airbus quotes optical viewing angles as incidence too,
and reading those as off-nadir errs the same way.

Being catalogued does not mean an imager is still tasked. Counting a
retired imager also over-reports observed time.

Wrong input raises `CatalogError`: an unknown sensor, an off-nadir angle
outside (0, 90), a duplicate NORAD id, a missing field or blank text.
"""

from __future__ import annotations

import pathlib
import tomllib
from typing import Any

from .model import Imager

DEFAULT_CATALOG = pathlib.Path(__file__).with_name("imaging.toml")
SENSORS = frozenset({"EO", "SAR"})
REQUIRED_FIELDS = ("norad_id", "name", "sensor", "max_off_nadir_deg", "basis")


class CatalogError(ValueError):
    """The catalog would make a pass prediction wrong, so it is refused."""


def load_catalog(path: str | pathlib.Path = DEFAULT_CATALOG) -> list[Imager]:
    with open(path, "rb") as fh:
        entries = tomllib.load(fh).get("imager", [])
    if not entries:
        raise CatalogError(f"{path}: no imagers catalogued")
    imagers = [_imager(entry) for entry in entries]
    _refuse_duplicates(imagers)
    return imagers


def _imager(entry: dict[str, Any]) -> Imager:
    missing = [field for field in REQUIRED_FIELDS if field not in entry]
    if missing:
        raise CatalogError(f"catalog entry {entry.get('name', '?')!r} is missing {', '.join(missing)}")
    imager = Imager(
        norad_id=int(entry["norad_id"]),
        name=str(entry["name"]),
        sensor=str(entry["sensor"]),
        max_off_nadir_deg=float(entry["max_off_nadir_deg"]),
        gsd_m=float(entry["gsd_m"]) if "gsd_m" in entry else None,
        basis=str(entry["basis"]),
    )
    _validate(imager)
    return imager


def _validate(imager: Imager) -> None:
    label = f"catalog entry {imager.norad_id} {imager.name!r}"
    if imager.sensor not in SENSORS:
        raise CatalogError(f"{label}: sensor {imager.sensor!r} is not one of {sorted(SENSORS)}")
    if not 0.0 < imager.max_off_nadir_deg < 90.0:
        raise CatalogError(f"{label}: max_off_nadir_deg {imager.max_off_nadir_deg} is outside (0, 90)")
    if imager.gsd_m is not None and imager.gsd_m <= 0.0:
        raise CatalogError(f"{label}: gsd_m {imager.gsd_m} must be positive")
    for field in ("name", "basis"):
        if not getattr(imager, field).strip():
            raise CatalogError(f"{label}: {field} is blank")


def _refuse_duplicates(imagers: list[Imager]) -> None:
    seen: set[int] = set()
    for imager in imagers:
        if imager.norad_id in seen:
            raise CatalogError(f"duplicate norad_id {imager.norad_id} in catalog")
        seen.add(imager.norad_id)
