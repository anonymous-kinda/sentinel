"""A record is found by the leading hex digits of its sha256, through the index.

The sync agent asks `has(prefix)` for every record of every event each time
the hub's manifest changes. A lookup that scans the table makes that cost
events x CDMs row reads per manifest change; one that searches the primary
key's index costs a few page reads per lookup. The query plan says which
one SQLite runs, so the proof does not depend on timing.
"""

import hashlib

import pytest

from sentinel.conjunction.store import CdmRow, ConjunctionStore


def row(n: int) -> CdmRow:
    raw = f"CDM {n}".encode()
    return CdmRow(
        sha256=hashlib.sha256(raw).hexdigest(), raw=raw, message_id=f"M{n}", originator="TEST", creation_date=None,
        tca="2026-09-24T07:00:00+00:00", primary_id="1", secondary_id="2", event_id="E", data_class="REAL",
        source="test", received_at="2026-09-23T12:00:00+00:00", warnings=[], hbr_source=None,
    )


@pytest.fixture
def store():
    store = ConjunctionStore()
    for n in range(50):
        store.add_cdm(row(n))
    return store


def query_plans(store: ConjunctionStore, lookup) -> list[str]:
    """What SQLite does for each statement `lookup` runs (the statements are read from the connection itself)."""
    statements: list[str] = []
    store._db.set_trace_callback(statements.append)
    try:
        lookup()
    finally:
        store._db.set_trace_callback(None)
    assert statements, "the lookup ran no SQL"
    return [detail for sql in statements for *_, detail in store._db.execute("EXPLAIN QUERY PLAN " + sql)]


@pytest.mark.parametrize("lookup", ["has_cdm_prefix", "cdm_by_prefix"])
def test_a_prefix_lookup_searches_the_primary_key_index_and_never_scans(store, lookup):
    prefix = row(7).sha256[:16]
    plans = query_plans(store, lambda: getattr(store, lookup)(prefix))
    assert all(plan.startswith("SEARCH cdm_messages USING") for plan in plans), plans
    assert not any("SCAN" in plan for plan in plans), plans


@pytest.mark.parametrize("length", [1, 16, 63, 64])
def test_a_prefix_finds_the_record_it_leads(store, length):
    wanted = row(7)
    prefix = wanted.sha256[:length]
    found = store.cdm_by_prefix(prefix)
    assert found is not None and found.sha256.startswith(prefix)
    assert store.has_cdm_prefix(prefix)
    if length >= 16:
        assert found.sha256 == wanted.sha256


def test_a_record_at_the_top_of_the_hex_range_is_found():
    """'f' is the last hex digit: the range above a prefix ending in it must still include it."""
    store = ConjunctionStore()
    top = next(r for r in (row(n) for n in range(1000)) if r.sha256.startswith("ff"))
    store.add_cdm(top)
    for prefix in ("f", "ff", top.sha256[:16], top.sha256):
        assert store.cdm_by_prefix(prefix) == top, prefix


@pytest.mark.parametrize("prefix", ["", "%", "_", "ABCDEF", "g", "0x1", "a%", "a_"])
def test_anything_but_lowercase_hex_names_no_record(store, prefix):
    assert store.cdm_by_prefix(prefix) is None
    assert not store.has_cdm_prefix(prefix)


def test_a_prefix_no_record_has_finds_nothing(store):
    held = {row(n).sha256[:4] for n in range(50)}
    absent = next(p for p in (f"{n:04x}" for n in range(0x10000)) if p not in held)
    assert store.cdm_by_prefix(absent) is None
    assert not store.has_cdm_prefix(absent)
