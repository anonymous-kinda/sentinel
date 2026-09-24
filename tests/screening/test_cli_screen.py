"""`sentinel screen`: a table that says what it is, and DERIVED CDMs on request."""

import json
import re

from sentinel import cli
from sentinel.cdm import parse, validate
from sentinel.screening.screen import screen

from .conftest import WINDOW_START, WV3, crossing_object

START = "2026-09-24T06:00:00Z"
REFUSED = "Pc: refused — element sets have no covariance"
A_PC_NUMBER = re.compile(r"\bPc\b[^\n]*?\d")


def write_elements(tmp_path, objects):
    path = tmp_path / "elements.json"
    path.write_text(json.dumps(objects))
    return path


def test_each_approach_is_listed_with_its_pc_refused_and_written_as_a_derived_cdm(tmp_path, capsys, snapshot):
    crosser = crossing_object(snapshot[WV3], 90.0)
    elements = write_elements(tmp_path, [snapshot[WV3], crosser])
    out = tmp_path / "cdms"
    argv = ["screen", "--primary", "40115", "--hours", "6", "--threshold-km", "10", "--elements", str(elements)]
    assert cli.main([*argv, "--out", str(out), "--start", START]) == 0

    text = capsys.readouterr().out
    expected = screen(WV3, {WV3: snapshot[WV3], 99115: crosser}, WINDOW_START, 6.0, 10.0).approaches
    rows = [line for line in text.splitlines() if REFUSED in line]
    assert len(rows) == len(expected) >= 2
    first = expected[0]
    assert "99115" in rows[0] and "CROSSER 90 (TEST)" in rows[0]
    assert f"{first.tca:%Y-%m-%dT%H:%M:%S}" in rows[0]
    assert f"{first.miss_distance_km:.3f}" in rows[0] and f"{first.relative_speed_km_s:.3f}" in rows[0]
    assert text.startswith("DEMONSTRATION MODE")
    assert A_PC_NUMBER.search(text) is None, "no probability, anywhere in the output"

    files = sorted(out.glob("*.cdm"))
    assert len(files) == len(expected)
    assert f"wrote {len(files)} DERIVED CDMs to {out}" in text
    for path in files:
        message = parse(path.read_text())
        assert message.originator == "SENTINEL-SCREENING"
        assert {w.code for w in validate(message)} == {"COVARIANCE_ABSENT"}


def test_nothing_within_the_threshold_is_said_plainly_on_the_bundled_snapshot(capsys):
    assert cli.main(["screen", "--primary", "40115", "--hours", "24", "--start", START]) == 0
    text = capsys.readouterr().out
    assert "no close approaches within 5.000 km" in text
    assert "166 objects" in text and "WORLDVIEW-3" in text
    assert REFUSED not in text


def test_an_unknown_primary_is_refused_with_its_reason(tmp_path, capsys, snapshot):
    elements = write_elements(tmp_path, [snapshot[WV3]])
    assert cli.main(["screen", "--primary", "12345", "--elements", str(elements), "--start", START]) == 2
    assert "UNKNOWN_PRIMARY" in capsys.readouterr().err


def test_skipped_objects_are_named_in_the_report(tmp_path, capsys, snapshot):
    decays = {**snapshot[WV3], "NORAD_CAT_ID": 99117, "ECCENTRICITY": 0.3, "MEAN_ANOMALY": 180.0}
    elements = write_elements(tmp_path, [snapshot[WV3], decays])
    assert cli.main(["screen", "--primary", "40115", "--elements", str(elements), "--start", START]) == 0
    text = capsys.readouterr().out
    assert re.search(r"skipped\s+99117 PROPAGATION_FAILED", text)
