"""The unit: validated on the way in, and kept on this node only.

Wrong input raises UnitRejected naming the field: a unit in the wrong
place, or with no time to react, would make every answer wrong. The unit
is written to one file, readable by the node's own user and nobody else.
"""

import json
import math
import os
import pathlib
import stat

import pytest

from sentinel.passes.model import Unit
from sentinel.passes.unit import UnitFile, UnitRejected, unit_from_dict, unit_to_dict

VALID = {"unit_id": "EX-UNIT-1", "lat_deg": 35.26, "lon_deg": -116.68, "alt_m": 700.0, "reaction_time_min": 30.0}


def test_a_valid_body_becomes_a_unit_and_round_trips():
    unit = unit_from_dict(VALID)
    assert unit == Unit("EX-UNIT-1", 35.26, -116.68, 700.0, 30.0)
    assert unit_to_dict(unit) == VALID


def test_altitude_and_reaction_time_take_the_model_defaults():
    unit = unit_from_dict({"unit_id": "EX", "lat_deg": 0, "lon_deg": 0})
    assert (unit.alt_m, unit.reaction_time_min) == (0.0, 30.0)
    assert isinstance(unit.lat_deg, float)


@pytest.mark.parametrize(
    "change,field",
    [
        ({"lat_deg": 90.01}, "lat_deg"),
        ({"lat_deg": -90.01}, "lat_deg"),
        ({"lon_deg": 180.01}, "lon_deg"),
        ({"lon_deg": -180.01}, "lon_deg"),
        ({"reaction_time_min": 0.0}, "reaction_time_min"),
        ({"reaction_time_min": -5.0}, "reaction_time_min"),
        ({"unit_id": ""}, "unit_id"),
        ({"unit_id": "   "}, "unit_id"),
        ({"unit_id": 7}, "unit_id"),
        ({"unit_id": "x" * 65}, "unit_id"),
        ({"lat_deg": "35.26"}, "lat_deg"),
        ({"lat_deg": True}, "lat_deg"),
        ({"lon_deg": math.nan}, "lon_deg"),
        ({"alt_m": math.inf}, "alt_m"),
        ({"alt_m": None}, "alt_m"),
        ({"lat": 35.26}, "lat"),
    ],
)
def test_wrong_input_is_rejected_naming_the_field(change, field):
    with pytest.raises(UnitRejected) as exc:
        unit_from_dict({**VALID, **change})
    assert exc.value.field == field


@pytest.mark.parametrize("missing", ["unit_id", "lat_deg", "lon_deg"])
def test_a_missing_required_field_is_rejected(missing):
    body = {k: v for k, v in VALID.items() if k != missing}
    with pytest.raises(UnitRejected) as exc:
        unit_from_dict(body)
    assert exc.value.field == missing


def test_the_boundaries_themselves_are_valid():
    unit_from_dict({**VALID, "lat_deg": 90, "lon_deg": -180})
    unit_from_dict({**VALID, "lat_deg": -90, "lon_deg": 180})


def test_a_body_that_is_not_an_object_is_rejected():
    with pytest.raises(UnitRejected):
        unit_from_dict([VALID])


def test_rejection_messages_never_echo_the_coordinates():
    with pytest.raises(UnitRejected) as exc:
        unit_from_dict({**VALID, "lat_deg": 91.2345})
    assert "91.2345" not in str(exc.value)


# ------------------------------------------------------------------ the file
def test_the_file_is_readable_by_the_node_user_only(tmp_path):
    units = UnitFile(tmp_path / "unit.json")
    units.save(unit_from_dict(VALID))
    assert stat.S_IMODE((tmp_path / "unit.json").stat().st_mode) == 0o600
    assert json.loads((tmp_path / "unit.json").read_text()) == VALID


def test_the_unit_survives_a_restart_and_clears(tmp_path):
    UnitFile(tmp_path / "unit.json").save(unit_from_dict(VALID))
    again = UnitFile(tmp_path / "unit.json")
    assert again.load() == unit_from_dict(VALID)
    again.clear()
    assert again.load() is None and not (tmp_path / "unit.json").exists()
    again.clear()  # idempotent


def test_no_file_means_no_unit(tmp_path):
    assert UnitFile(tmp_path / "unit.json").load() is None


def test_a_replacement_keeps_the_file_private(tmp_path):
    units = UnitFile(tmp_path / "unit.json")
    units.save(unit_from_dict(VALID))
    units.save(unit_from_dict({**VALID, "unit_id": "EX-UNIT-2"}))
    assert stat.S_IMODE((tmp_path / "unit.json").stat().st_mode) == 0o600
    assert units.load().unit_id == "EX-UNIT-2"
    assert [p.name for p in tmp_path.iterdir()] == ["unit.json"], "no temporary file left behind"


@pytest.fixture
def disk_calls(monkeypatch):
    """Every fsync and rename the unit file makes, in order. An fsync is
    recorded as what its descriptor is: the directory, or a file of n bytes."""
    calls = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd):
        info = os.fstat(fd)
        calls.append(("fsync", "directory", info.st_ino) if stat.S_ISDIR(info.st_mode) else ("fsync", "file", info.st_size))
        real_fsync(fd)

    def replace(src, dst):
        calls.append(("replace", pathlib.Path(dst).name))
        real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    return calls


def test_a_saved_unit_is_on_disk_before_it_replaces_the_old_one(tmp_path, disk_calls):
    """Power lost at any point leaves the old unit or the new one, never an
    empty file: the new contents are flushed and fsynced before the rename,
    and the directory is fsynced after it so the rename itself survives."""
    UnitFile(tmp_path / "unit.json").save(unit_from_dict(VALID))
    written = len((tmp_path / "unit.json").read_bytes())
    assert disk_calls == [
        ("fsync", "file", written),
        ("replace", "unit.json"),
        ("fsync", "directory", tmp_path.stat().st_ino),
    ]


def test_a_cleared_unit_stays_cleared_after_a_power_cut(tmp_path, disk_calls):
    units = UnitFile(tmp_path / "unit.json")
    units.save(unit_from_dict(VALID))
    disk_calls.clear()
    units.clear()
    assert disk_calls == [("fsync", "directory", tmp_path.stat().st_ino)]
    units.clear()
    UnitFile(tmp_path / "absent" / "unit.json").clear()
    assert len(disk_calls) == 1, "clearing no unit changes nothing, so syncs nothing"


def test_a_failed_fsync_keeps_the_old_unit_and_leaves_no_temporary_file(tmp_path, monkeypatch):
    units = UnitFile(tmp_path / "unit.json")
    units.save(unit_from_dict(VALID))

    def failing_fsync(fd):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError):
        units.save(unit_from_dict({**VALID, "unit_id": "EX-UNIT-2"}))
    assert units.load().unit_id == VALID["unit_id"]
    assert [p.name for p in tmp_path.iterdir()] == ["unit.json"]


def test_a_corrupt_file_is_refused_not_guessed(tmp_path):
    (tmp_path / "unit.json").write_text('{"unit_id": "EX", "lat_deg": 123}')
    with pytest.raises(UnitRejected):
        UnitFile(tmp_path / "unit.json").load()
    (tmp_path / "unit.json").write_text("not json")
    with pytest.raises(UnitRejected):
        UnitFile(tmp_path / "unit.json").load()
