"""The OPSEC scenario's leak detector must see the unit wherever it could be.

"The hub never saw the coordinates" is only evidence if the detector would
have found them in any form they could travel in: text at any precision
worth leaking, JSON, CBOR (the operator-data codec), raw IEEE-754 bytes,
and the unit's Earth-fixed position. It must also stay silent on what
legitimately crosses the link - element sets and CDMs - or every run fails.
"""

import datetime as dt
import json
import pathlib
import struct

import cbor2

from harness.opsec import SyncLedger, find_leaks, leak_patterns, scan_tree
from sentinel.conjunction.exercise import generate
from sentinel.passes.model import Unit
from sentinel.passes.topocentric import Site

UNIT = {"unit_id": "EX-OPSEC-UNIT-7", "lat_deg": 35.26417, "lon_deg": -116.68273, "alt_m": 701.0, "reaction_time_min": 30.0}
PATTERNS = leak_patterns(UNIT)
SNAPSHOT = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "omm" / "celestrak-resource-20260924.json"


def test_it_finds_the_unit_as_the_node_stores_it():
    assert "unit_id" in find_leaks(json.dumps(UNIT).encode(), PATTERNS)
    assert {"lat_deg text", "lon_deg text"} <= set(find_leaks(json.dumps(UNIT).encode(), PATTERNS))


def test_it_finds_rounded_coordinates():
    assert find_leaks(b"unit near 35.2642, -116.6827", PATTERNS)
    assert find_leaks(b'{"lat": 35.264170}', PATTERNS)


def test_it_finds_binary_coordinates_in_cbor_and_raw_floats():
    assert "lat_deg float64 big-endian" in find_leaks(cbor2.dumps({"lat": 35.26417}), PATTERNS)
    assert "lon_deg float64 little-endian" in find_leaks(struct.pack("<d", -116.68273), PATTERNS)
    assert "lat_deg float32 big-endian" in find_leaks(struct.pack(">f", 35.26417), PATTERNS)


def test_it_finds_the_earth_fixed_position():
    site = Site.from_unit(Unit(**UNIT))
    x_km = site.ecef_km[0]
    assert find_leaks(f"x={x_km:.3f} km".encode(), PATTERNS)
    assert find_leaks(f"{x_km * 1000:.1f}".encode(), PATTERNS)


def test_it_stays_silent_on_what_legitimately_crosses_the_link():
    corpus = SNAPSHOT.read_bytes() + b"".join(i.kvn.encode() for i in generate(dt.datetime(2026, 9, 24, 6, tzinfo=dt.UTC)))
    assert find_leaks(corpus, PATTERNS) == []


def test_a_tree_scan_names_each_file_that_holds_the_unit(tmp_path):
    (tmp_path / "var").mkdir()
    (tmp_path / "var" / "unit.json").write_text(json.dumps(UNIT))
    (tmp_path / "var" / "clean.log").write_text("nothing here")
    (tmp_path / "db.sqlite").write_bytes(cbor2.dumps({"lon": -116.68273}))
    found = scan_tree(tmp_path, PATTERNS)
    assert set(found) == {"var/unit.json", "db.sqlite"}
    assert "unit_id" in found["var/unit.json"]


# ------------------------------------------------ arrivals, as the edge records them
def arrival(item_id: str) -> dict:
    return {"event_id": item_id, "sha": item_id.encode().hex()[:16], "status": "accepted"}


def sync_status(fetched: list[dict]) -> dict:
    """GET /api/sync on an edge: the last 50 arrivals and a running total."""
    return {"arrivals": fetched[-50:], "arrivals_total": len(fetched)}


def test_the_ledger_keeps_every_arrival_across_overlapping_status_reads():
    fetched = [arrival(f"omm:{n}") for n in range(30)] + [arrival(f"EV-{n}") for n in range(40)]
    ledger = SyncLedger()
    for seen in (0, 20, 45, 70, 70):
        ledger.record(sync_status(fetched[:seen]))
    assert ledger.arrivals == fetched
    assert ledger.unseen == 0
    assert ledger.items("omm:") == {f"omm:{n}" for n in range(30)}


def test_arrivals_fetched_before_the_first_read_still_count():
    """The race the hub-side count lost: the edge fetched before anyone listened."""
    ledger = SyncLedger()
    ledger.record(sync_status([arrival(f"omm:{n}") for n in range(38)]))
    assert len(ledger.items("omm:")) == 38


def test_arrivals_that_scrolled_out_of_the_window_unseen_are_counted_not_guessed():
    ledger = SyncLedger()
    ledger.record(sync_status([arrival(f"omm:{n}") for n in range(60)]))
    assert ledger.unseen == 10
    assert ledger.items("omm:") == {f"omm:{n}" for n in range(10, 60)}


def test_an_item_fetched_twice_counts_once():
    ledger = SyncLedger()
    ledger.record(sync_status([arrival("omm:1"), arrival("omm:1"), arrival("EV-1")]))
    assert ledger.items("omm:") == {"omm:1"}
