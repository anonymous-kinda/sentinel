"""Element sets: the public OMM snapshot, and pairing it with the catalog."""

import datetime as dt
import json
import logging
import pathlib

import pytest

from sentinel.passes.catalog import load_catalog
from sentinel.passes.elements import (
    ElementSetError,
    SkipReason,
    epoch_utc,
    load_omm,
    match_catalog,
    mean_altitude_km,
)
from sentinel.passes.model import Imager

SNAPSHOT = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "omm" / "celestrak-resource-20260924.json"


@pytest.fixture(scope="module")
def snapshot():
    return load_omm(SNAPSHOT)


def imager(norad_id, name, sensor="EO"):
    return Imager(norad_id=norad_id, name=name, sensor=sensor, max_off_nadir_deg=30.0, basis="Planning assumption: test.")


def write_omm(tmp_path, records):
    path = tmp_path / "omm.json"
    path.write_text(json.dumps(records))
    return path


def test_the_snapshot_loads_keyed_by_norad_id(snapshot):
    assert len(snapshot) == 167
    assert snapshot[40115]["OBJECT_NAME"] == "WORLDVIEW-3 (WV-3)"


def test_a_snapshot_that_is_not_a_list_is_refused(tmp_path):
    with pytest.raises(ElementSetError, match="list"):
        load_omm(write_omm(tmp_path, {"OBJECT_NAME": "X"}))


def test_an_element_set_missing_a_field_sgp4_needs_is_refused(tmp_path, snapshot):
    record = {k: v for k, v in snapshot[40115].items() if k != "MEAN_MOTION"}
    with pytest.raises(ElementSetError, match="MEAN_MOTION"):
        load_omm(write_omm(tmp_path, [record]))


def test_a_duplicate_norad_id_is_refused(tmp_path, snapshot):
    with pytest.raises(ElementSetError, match="duplicate"):
        load_omm(write_omm(tmp_path, [snapshot[40115], snapshot[40115]]))


def test_the_epoch_is_read_as_utc(snapshot):
    assert epoch_utc(snapshot[40115]) == dt.datetime(2026, 9, 23, 22, 37, 2, 779392, tzinfo=dt.UTC)


# Nominal altitudes from the operators' own published figures. Mean
# altitude from mean motion should land within a few kilometres of them.
PUBLISHED_ALTITUDES = [
    (39084, 705.0),    # Landsat 8 (USGS)
    (40697, 786.0),    # Sentinel-2A (ESA)
    (39634, 693.0),    # Sentinel-1A (ESA)
    (40115, 617.0),    # WorldView-3 (vendor datasheet)
    (31698, 514.8),    # TerraSAR-X (eoPortal)
]


@pytest.mark.parametrize("norad_id,published_km", PUBLISHED_ALTITUDES)
def test_mean_altitude_from_mean_motion_matches_published_altitudes(snapshot, norad_id, published_km):
    assert mean_altitude_km(snapshot[norad_id]) == pytest.approx(published_km, abs=10.0)


def test_a_non_positive_mean_motion_is_refused(snapshot):
    with pytest.raises(ElementSetError, match="MEAN_MOTION"):
        mean_altitude_km({**snapshot[40115], "MEAN_MOTION": 0.0})


def test_every_catalogued_imager_is_in_the_vendored_snapshot(snapshot):
    match = match_catalog(load_catalog(), snapshot)
    assert match.skipped == []
    assert len(match.imagers) == len(load_catalog())
    assert set(match.element_sets) == {i.norad_id for i in match.imagers}


def test_a_catalog_name_matches_the_object_name_up_to_a_word_boundary(snapshot):
    match = match_catalog([imager(40115, "WORLDVIEW-3"), imager(38338, "ARIRANG-3")], snapshot)
    assert [i.norad_id for i in match.imagers] == [40115, 38338]
    assert match.element_sets[40115]["OBJECT_NAME"] == "WORLDVIEW-3 (WV-3)"


def test_a_missing_element_set_is_skipped_with_a_reason_and_a_warning(snapshot, caplog):
    caplog.set_level(logging.WARNING, logger="sentinel.passes.elements")
    match = match_catalog([imager(99999, "NOT CATALOGUED")], snapshot)
    assert match.imagers == []
    (skipped,) = match.skipped
    assert skipped.imager.norad_id == 99999
    assert skipped.reason is SkipReason.MISSING
    record = caplog.records[-1]
    assert record.getMessage() == "Imager skipped"
    assert record.fields == {"norad_id": 99999, "name": "NOT CATALOGUED", "reason": "missing", "object_name": None}


def test_an_id_whose_object_name_differs_is_skipped_not_trusted(snapshot, caplog):
    caplog.set_level(logging.WARNING, logger="sentinel.passes.elements")
    match = match_catalog([imager(40115, "WORLDVIEW-2")], snapshot)
    (skipped,) = match.skipped
    assert skipped.reason is SkipReason.NAME_MISMATCH
    assert skipped.object_name == "WORLDVIEW-3 (WV-3)"
    assert caplog.records[-1].fields["reason"] == "name_mismatch"


def test_a_prefix_that_stops_mid_word_is_a_mismatch(snapshot):
    """SKYSAT-C1 is a prefix of SKYSAT-C10: a wrong id must not pass."""
    assert snapshot[42988]["OBJECT_NAME"] == "SKYSAT-C10"
    match = match_catalog([imager(42988, "SKYSAT-C1")], snapshot)
    assert [s.reason for s in match.skipped] == [SkipReason.NAME_MISMATCH]


def test_matched_and_skipped_together_account_for_every_imager(snapshot):
    imagers = [imager(40115, "WORLDVIEW-3"), imager(99999, "GONE"), imager(42988, "SKYSAT-C1")]
    match = match_catalog(imagers, snapshot)
    assert len(match.imagers) + len(match.skipped) == len(imagers)
