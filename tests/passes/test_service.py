"""The node's pass service: one unit, its windows and gaps, kept on this node.

What the service must never do is as important as what it computes: the
unit is stored in one private file, published nowhere, logged nowhere,
and the only bus message is a coordinate-free "passes.updated".
"""

import asyncio
import dataclasses
import datetime as dt
import json
import logging

import pytest

from sentinel.bus import InProcessBus
from sentinel.clock import FixedClock
from sentinel.passes.catalog import load_catalog
from sentinel.passes.element_store import ElementStore, canonical_bytes
from sentinel.passes.gaps import GAP_LABEL
from sentinel.passes.model import PassWindow, Unit
from sentinel.passes.providers.skyfield_local import SkyfieldProvider
from sentinel.passes.service import MAX_HOURS, MIN_HOURS, NoUnit, PassService
from sentinel.passes.unit import UnitFile

from .exercise import SNAPSHOT, START

NODE = "edge-alpha"
WV3 = 40115
UNIT = Unit("EX-UNIT-7", lat_deg=35.26417, lon_deg=-116.68273, alt_m=701.0, reaction_time_min=30.0)
SECRETS = ("EX-UNIT-7", "35.26417", "-116.68273", "35.2642", "-116.6827")


class Counting:
    """A provider factory that counts builds and window requests."""

    def __init__(self, factory=SkyfieldProvider):
        self.factory = factory
        self.builds: list[dict] = []
        self.calls = 0

    def __call__(self, element_sets):
        self.builds.append(dict(element_sets))
        inner = self.factory(element_sets)
        outer = self

        class Provider:
            name = inner.name

            def windows(self, unit, imagers, start, end):
                outer.calls += 1
                return inner.windows(unit, imagers, start, end)

        return Provider()


class NoPasses:
    name = "no-passes"

    def __init__(self, element_sets):
        pass

    def windows(self, unit, imagers, start, end):
        return []


def snapshot_store(without=()) -> ElementStore:
    store = ElementStore()
    for obj in json.loads(SNAPSHOT.read_text()):
        if obj["NORAD_CAT_ID"] not in without:
            store.add(canonical_bytes(obj), "test")
    return store


@dataclasses.dataclass
class Harness:
    service: PassService
    store: ElementStore
    clock: FixedClock
    messages: list
    units: UnitFile


def make(tmp_path, store=None, provider_factory=SkyfieldProvider, now=START) -> Harness:
    bus, messages = InProcessBus(), []

    async def capture(msg):
        messages.append(msg)

    asyncio.run(bus.subscribe(">", capture))
    store = store if store is not None else snapshot_store()
    clock = FixedClock(now)
    units = UnitFile(tmp_path / "unit.json")
    service = PassService(store, load_catalog(), clock, units, bus, NODE, provider_factory=provider_factory)
    return Harness(service, store, clock, messages, units)


@pytest.fixture
def node(tmp_path):
    h = make(tmp_path)
    asyncio.run(h.service.set_unit(UNIT))
    return h


# ------------------------------------------------------------------ the unit
def test_no_unit_means_no_passes(tmp_path):
    h = make(tmp_path)
    assert h.service.unit is None
    with pytest.raises(NoUnit):
        h.service.passes(24)


def test_the_unit_is_kept_in_one_private_file_and_survives_a_restart(node, tmp_path):
    assert node.service.unit == UNIT
    again = PassService(node.store, load_catalog(), node.clock, UnitFile(tmp_path / "unit.json"), InProcessBus(), NODE)
    assert again.unit == UNIT
    asyncio.run(again.clear_unit())
    assert again.unit is None and not (tmp_path / "unit.json").exists()


def test_the_only_message_is_a_coordinate_free_passes_updated(node):
    asyncio.run(node.service.clear_unit())
    asyncio.run(node.service.elements_changed())
    assert [m.subject for m in node.messages] == [f"node.{NODE}.passes.updated"] * 3
    assert [json.loads(m.data)["reason"] for m in node.messages] == ["unit_set", "unit_cleared", "elements"]
    assert {m.headers["Sentinel-Kind"] for m in node.messages} == {"passes.updated"}
    for m in node.messages:
        text = m.data.decode() + json.dumps(m.headers)
        assert not any(secret in text for secret in SECRETS), text


def test_nothing_logged_carries_the_unit(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    h = make(tmp_path)
    asyncio.run(h.service.set_unit(UNIT))
    h.service.passes(24)
    h.service.catalog()
    asyncio.run(h.service.clear_unit())
    assert caplog.records, "the service does log"
    for record in caplog.records:
        text = record.getMessage() + json.dumps(getattr(record, "fields", {}), default=str)
        assert not any(secret in text for secret in SECRETS), text


def test_a_corrupt_unit_file_is_logged_and_not_guessed(tmp_path, caplog):
    (tmp_path / "unit.json").write_text('{"unit_id": "EX", "lat_deg": 123, "lon_deg": 0}')
    h = make(tmp_path)
    assert h.service.unit is None
    record = next(r for r in caplog.records if r.getMessage() == "Unit file unreadable")
    assert record.fields["field"] == "lat_deg"


def test_an_invalid_unit_is_refused_before_it_is_stored(tmp_path):
    h = make(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(h.service.set_unit(dataclasses.replace(UNIT, lat_deg=95.0)))
    assert h.service.unit is None and not (tmp_path / "unit.json").exists() and h.messages == []


# -------------------------------------------------------------- the answer
def test_windows_and_gaps_cover_the_requested_hours_from_this_minute(tmp_path):
    h = make(tmp_path, now=START + dt.timedelta(seconds=45))
    asyncio.run(h.service.set_unit(UNIT))
    report = h.service.passes(24)
    assert (report.start, report.end) == (START, START + dt.timedelta(hours=24))
    assert report.unit == UNIT and report.provider == "skyfield-local"
    assert len(report.imagers) == 38 and report.skipped == ()
    assert report.windows and [w.rise for w in report.windows] == sorted(w.rise for w in report.windows)
    assert report.gaps and all(g.label == GAP_LABEL for g in report.gaps)
    assert not any(g.low_confidence for g in report.gaps)
    gap = report.next_unobserved
    assert gap is not None and gap.duration_s >= UNIT.reaction_time_min * 60.0


def test_the_next_gap_counts_from_the_true_now_not_the_cached_minute(tmp_path):
    h = make(tmp_path, provider_factory=NoPasses, now=START + dt.timedelta(seconds=45))
    asyncio.run(h.service.set_unit(UNIT))
    report = h.service.passes(2)
    assert report.gaps[0].start == START
    assert report.next_unobserved.start == START + dt.timedelta(seconds=45)


def test_a_skipped_imager_makes_every_gap_low_confidence(tmp_path):
    h = make(tmp_path, store=snapshot_store(without={WV3}))
    asyncio.run(h.service.set_unit(UNIT))
    report = h.service.passes(24)
    assert [(s.imager.norad_id, s.reason.value) for s in report.skipped] == [(WV3, "missing")]
    assert len(report.imagers) == 37
    assert report.gaps and all(g.low_confidence for g in report.gaps)
    assert report.next_unobserved.low_confidence


def test_no_element_sets_at_all_is_one_low_confidence_gap_with_every_imager_skipped(tmp_path):
    h = make(tmp_path, store=ElementStore())
    asyncio.run(h.service.set_unit(UNIT))
    report = h.service.passes(6)
    assert report.windows == () and len(report.skipped) == 38 and report.imagers == ()
    assert [(g.duration_s, g.low_confidence) for g in report.gaps] == [(6 * 3600.0, True)]
    assert report.elements.oldest_age_days is None and report.elements.stale == 0


def test_element_ages_describe_the_sets_that_fed_the_answer(node):
    report = node.service.passes(24)
    latest = node.store.latest()
    ages = [(START - dt.datetime.fromisoformat(latest[i.norad_id]["EPOCH"]).replace(tzinfo=dt.UTC)).total_seconds() / 86400
            for i in report.imagers]
    assert report.elements.oldest_age_days == pytest.approx(max(ages))
    assert report.elements.newest_age_days == pytest.approx(min(ages))
    assert report.elements.stale == 0


@pytest.mark.parametrize("hours", [MIN_HOURS - 0.5, MAX_HOURS + 1])
def test_hours_outside_the_interface_range_are_refused(node, hours):
    assert (MIN_HOURS, MAX_HOURS) == (1, 72)
    with pytest.raises(ValueError):
        node.service.passes(hours)


def test_the_catalog_pairs_each_imager_with_its_element_set_age(tmp_path):
    h = make(tmp_path, store=snapshot_store(without={WV3}))
    entries, skipped = h.service.catalog()
    assert len(entries) == 37 and [s.imager.norad_id for s in skipped] == [WV3]
    first = entries[0]
    epoch = dt.datetime.fromisoformat(h.store.latest()[first.imager.norad_id]["EPOCH"]).replace(tzinfo=dt.UTC)
    assert first.element_epoch == epoch
    assert first.element_age_days == pytest.approx((START - epoch).total_seconds() / 86400)
    assert first.stale is False


# ------------------------------------------------------------------- caching
def test_the_answer_is_cached_per_unit_element_version_and_minute(tmp_path):
    counting = Counting()
    h = make(tmp_path, provider_factory=counting)
    asyncio.run(h.service.set_unit(UNIT))
    first = h.service.passes(24)
    h.clock.advance(30)
    assert h.service.passes(24).windows == first.windows
    assert counting.calls == 1, "same unit, same element sets, same minute"

    h.clock.advance(30)
    h.service.passes(24)
    assert counting.calls == 2, "a new minute"

    h.service.passes(12)
    assert counting.calls == 3, "a different interval"

    asyncio.run(h.service.set_unit(dataclasses.replace(UNIT, reaction_time_min=45.0)))
    h.service.passes(24)
    assert counting.calls == 4, "a different unit"
    assert len(counting.builds) == 1, "the provider is reused while the element sets are unchanged"


def test_a_new_element_set_rebuilds_the_provider_and_the_answer(node, tmp_path):
    counting = Counting()
    h = make(tmp_path, provider_factory=counting)
    asyncio.run(h.service.set_unit(UNIT))
    h.service.passes(24)
    wv3 = h.store.latest()[WV3]
    newer = {**wv3, "EPOCH": "2026-09-24T05:00:00.000000", "ELEMENT_SET_NO": wv3["ELEMENT_SET_NO"] + 1}
    h.store.add(canonical_bytes(newer), "sync:hub")
    h.service.passes(24)
    assert counting.calls == 2 and len(counting.builds) == 2
    assert counting.builds[-1][WV3]["EPOCH"] == "2026-09-24T05:00:00.000000"


def test_windows_carry_the_provider_contract(node):
    assert all(isinstance(w, PassWindow) for w in node.service.passes(6).windows)
