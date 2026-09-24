"""Element sets as sync records: one public OMM object per record.

The record's bytes are the object's canonical JSON, so hub and edge derive
the same sha256 from the same data - identity is content, not transport.
"""

import asyncio
import datetime as dt
import json
import pathlib

import pytest

from sentinel.clock import FixedClock
from sentinel.passes.element_store import (
    ElementRejected,
    ElementStore,
    canonical_bytes,
    default_snapshot,
)
from sentinel.passes.sync_adapter import ElementRecords

SNAPSHOT = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "omm" / "celestrak-resource-20260924.json"
NOW = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
WV3 = 40115


@pytest.fixture
def store():
    s = ElementStore()
    s.load_snapshot(SNAPSHOT, "celestrak")
    return s


def wv3_object() -> dict:
    return next(o for o in json.loads(SNAPSHOT.read_text()) if o["NORAD_CAT_ID"] == WV3)


def test_a_snapshot_becomes_one_record_per_object(store):
    assert len(store.latest()) == 167
    assert store.latest()[WV3]["OBJECT_NAME"].startswith("WORLDVIEW-3")


def test_identity_is_the_canonical_bytes_not_the_formatting():
    obj = wv3_object()
    assert canonical_bytes(obj) == canonical_bytes(json.loads(json.dumps(obj, indent=4)))


def test_the_same_record_twice_is_a_duplicate_and_a_newer_epoch_replaces(store):
    obj = wv3_object()
    assert store.add(canonical_bytes(obj), "test").status == "duplicate"
    newer = {**obj, "EPOCH": "2026-09-24T12:00:00.000000", "ELEMENT_SET_NO": obj["ELEMENT_SET_NO"] + 1}
    assert store.add(canonical_bytes(newer), "test").status == "accepted"
    assert store.latest()[WV3]["EPOCH"] == "2026-09-24T12:00:00.000000"
    older = {**obj, "EPOCH": "2026-09-20T00:00:00.000000"}
    assert store.add(canonical_bytes(older), "test").status == "superseded"
    assert store.latest()[WV3]["EPOCH"] == "2026-09-24T12:00:00.000000"


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda o: o.pop("MEAN_MOTION"), "MISSING_FIELD"),
        (lambda o: o.update(NORAD_CAT_ID="x"), "INVALID_FIELD"),
        (lambda o: o.update(EPOCH="yesterday"), "INVALID_FIELD"),
        (lambda o: o.update(MEAN_MOTION=-1.0), "INVALID_FIELD"),
    ],
)
def test_wrong_element_sets_are_rejected_with_a_named_reason(mutate, code):
    obj = wv3_object()
    mutate(obj)
    with pytest.raises(ElementRejected) as exc:
        ElementStore().add(canonical_bytes(obj), "test")
    assert exc.value.code == code


def test_not_json_is_rejected():
    with pytest.raises(ElementRejected) as exc:
        ElementStore().add(b"not json", "test")
    assert exc.value.code == "PARSE_ERROR"


def test_the_manifest_offers_each_element_set_with_its_staleness_deadline(store):
    records = ElementRecords(store, FixedClock(NOW))
    [entry] = [m for m in records.manifest() if m["e"] == f"omm:{WV3}"]
    epoch = dt.datetime.fromisoformat(store.latest()[WV3]["EPOCH"]).replace(tzinfo=dt.UTC)
    assert entry["dl"] == int((epoch + dt.timedelta(days=3)).timestamp()), "deadline: when the set goes stale"
    assert entry["q"] == 0, "routine: urgent CDMs cross the link first"
    [[sha16, size, created]] = entry["c"]
    raw, headers = records.get(sha16)
    assert len(raw) == size and headers["Sentinel-Event-Id"] == f"omm:{WV3}" and headers["Sentinel-Data-Class"] == "REAL"
    assert records.has(sha16)


def test_an_edge_ingests_what_the_hub_serves_and_knows_it_has_it(store):
    hub = ElementRecords(store, FixedClock(NOW))
    edge = ElementRecords(ElementStore(), FixedClock(NOW))
    [entry] = [m for m in hub.manifest() if m["e"] == f"omm:{WV3}"]
    sha16 = entry["c"][0][0]
    raw, headers = hub.get(sha16)
    assert not edge.has(sha16)
    outcome = asyncio.run(edge.ingest(raw, "hub", "REAL", headers["Sentinel-Event-Id"]))
    assert outcome["status"] == "accepted" and outcome["sha256"] == headers["Sentinel-Sha256"]
    assert edge.has(sha16)


def test_a_rejected_record_is_reported_not_raised_to_the_sync_agent():
    edge = ElementRecords(ElementStore(), FixedClock(NOW))
    outcome = asyncio.run(edge.ingest(b"{}", "hub", "REAL", "omm:1"))
    assert outcome["status"] == "rejected" and outcome["code"] == "MISSING_FIELD"


# ------------------------------------------------------- node service support
def test_the_version_moves_only_when_an_element_set_is_accepted():
    s = ElementStore()
    assert s.version == 0
    obj = wv3_object()
    s.add(canonical_bytes(obj), "test")
    assert s.version == 1
    s.add(canonical_bytes(obj), "test")  # duplicate
    s.add(canonical_bytes({**obj, "EPOCH": "2026-09-20T00:00:00.000000"}), "test")  # superseded
    with pytest.raises(ElementRejected):
        s.add(b"{}", "test")
    assert s.version == 1, "a cache keyed on the version stays valid until the data changes"


def test_loading_a_snapshot_counts_what_was_accepted_and_what_was_rejected(tmp_path):
    good = json.loads(SNAPSHOT.read_text())
    bad = {**good[0], "MEAN_MOTION": "fast"}
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps([*good, bad]))
    loaded = ElementStore().load_snapshot(path, "test")
    assert (loaded.accepted, loaded.rejected) == (167, 1)


def test_the_vendored_snapshot_is_found_in_a_checkout_or_under_sentinel_fixtures(monkeypatch, tmp_path):
    monkeypatch.delenv("SENTINEL_FIXTURES", raising=False)
    assert default_snapshot() == SNAPSHOT
    monkeypatch.setenv("SENTINEL_FIXTURES", str(tmp_path))
    assert default_snapshot() == tmp_path / "omm" / SNAPSHOT.name


def test_an_accepted_record_tells_the_node_and_nothing_else_does(store):
    calls = []

    async def changed():
        calls.append("changed")

    hub = ElementRecords(store, FixedClock(NOW))
    edge = ElementRecords(ElementStore(), FixedClock(NOW), on_accepted=changed)
    [entry] = [m for m in hub.manifest() if m["e"] == f"omm:{WV3}"]
    raw, _ = hub.get(entry["c"][0][0])
    asyncio.run(edge.ingest(raw, "hub", "REAL", f"omm:{WV3}"))
    asyncio.run(edge.ingest(raw, "hub", "REAL", f"omm:{WV3}"))  # duplicate
    asyncio.run(edge.ingest(b"{}", "hub", "REAL", "omm:1"))     # rejected
    assert calls == ["changed"]
