"""The imaging catalog: which public imagers count, and how far each can look."""

import math

import pytest

from sentinel.passes.catalog import DEFAULT_CATALOG, CatalogError, load_catalog
from sentinel.passes.geometry import EARTH_RADIUS_KM

VALID = {
    "norad_id": 39084,
    "name": "LANDSAT 8",
    "sensor": "EO",
    "max_off_nadir_deg": 7.5,
    "gsd_m": 15.0,
    "basis": "Planning assumption: test entry.",
}


def toml_entry(fields: dict) -> str:
    lines = ["[[imager]]"]
    for key, value in fields.items():
        lines.append(f"{key} = {value!r}" if not isinstance(value, str) else f'{key} = "{value}"')
    return "\n".join(lines) + "\n"


def write_catalog(tmp_path, *entries: dict):
    path = tmp_path / "imaging.toml"
    path.write_text("\n".join(toml_entry(e) for e in entries))
    return path


def test_a_valid_entry_loads_as_an_imager(tmp_path):
    (imager,) = load_catalog(write_catalog(tmp_path, VALID))
    assert imager.norad_id == 39084
    assert imager.name == "LANDSAT 8"
    assert imager.sensor == "EO"
    assert imager.max_off_nadir_deg == 7.5
    assert imager.gsd_m == 15.0
    assert imager.basis == "Planning assumption: test entry."


def test_gsd_is_optional(tmp_path):
    entry = {k: v for k, v in VALID.items() if k != "gsd_m"}
    (imager,) = load_catalog(write_catalog(tmp_path, entry))
    assert imager.gsd_m is None


@pytest.mark.parametrize("sensor", ["IR", "eo", "", "LIDAR"])
def test_an_unknown_sensor_is_refused(tmp_path, sensor):
    with pytest.raises(CatalogError, match="sensor"):
        load_catalog(write_catalog(tmp_path, {**VALID, "sensor": sensor}))


@pytest.mark.parametrize("off_nadir", [0.0, -5.0, 90.0, 95.0])
def test_an_off_nadir_angle_outside_zero_to_ninety_is_refused(tmp_path, off_nadir):
    with pytest.raises(CatalogError, match="max_off_nadir_deg"):
        load_catalog(write_catalog(tmp_path, {**VALID, "max_off_nadir_deg": off_nadir}))


def test_a_duplicate_norad_id_is_refused(tmp_path):
    with pytest.raises(CatalogError, match="duplicate"):
        load_catalog(write_catalog(tmp_path, VALID, {**VALID, "name": "LANDSAT 8 AGAIN"}))


@pytest.mark.parametrize("missing", ["norad_id", "name", "sensor", "max_off_nadir_deg", "basis"])
def test_a_missing_required_field_is_refused(tmp_path, missing):
    entry = {k: v for k, v in VALID.items() if k != missing}
    with pytest.raises(CatalogError, match=missing):
        load_catalog(write_catalog(tmp_path, entry))


@pytest.mark.parametrize("field,value", [("basis", ""), ("name", "  "), ("gsd_m", 0.0), ("gsd_m", -1.0)])
def test_blank_text_or_a_non_positive_gsd_is_refused(tmp_path, field, value):
    with pytest.raises(CatalogError, match=field):
        load_catalog(write_catalog(tmp_path, {**VALID, field: value}))


def test_an_empty_catalog_is_refused(tmp_path):
    path = tmp_path / "imaging.toml"
    path.write_text("# nothing here\n")
    with pytest.raises(CatalogError, match="no imagers"):
        load_catalog(path)


def test_the_shipped_catalog_labels_every_angle_a_planning_assumption():
    imagers = load_catalog(DEFAULT_CATALOG)
    assert len(imagers) >= 20
    assert {i.sensor for i in imagers} == {"EO", "SAR"}
    for imager in imagers:
        assert "planning assumption" in imager.basis.lower(), imager.name


def test_the_shipped_catalog_reads_sar_incidence_as_off_nadir_and_says_so():
    for imager in load_catalog(DEFAULT_CATALOG):
        if imager.sensor == "SAR":
            assert "incidence" in imager.basis.lower(), imager.name


def swath_km(half_angle_deg: float, altitude_km: float) -> float:
    """Ground swath of a nadir-pointing imager on a spherical Earth."""
    theta = math.radians(half_angle_deg)
    nadir_to_edge = math.asin((EARTH_RADIUS_KM + altitude_km) / EARTH_RADIUS_KM * math.sin(theta)) - theta
    return 2 * EARTH_RADIUS_KM * nadir_to_edge


# Published nominal altitude and swath, a second figure from the same
# sources, which the catalogued half-angle must reproduce.
PUBLISHED_SWATHS = [
    ("LANDSAT 8", 705.0, 185.0),
    ("LANDSAT 9", 705.0, 185.0),
    ("SENTINEL-2A", 786.0, 290.0),
    ("SENTINEL-2B", 786.0, 290.0),
    ("SENTINEL-2C", 786.0, 290.0),
]


@pytest.mark.parametrize("name,altitude_km,published_swath_km", PUBLISHED_SWATHS)
def test_nadir_imagers_half_angles_reproduce_their_published_swaths(name, altitude_km, published_swath_km):
    by_name = {i.name: i for i in load_catalog(DEFAULT_CATALOG)}
    swath = swath_km(by_name[name].max_off_nadir_deg, altitude_km)
    assert swath == pytest.approx(published_swath_km, rel=0.03)
