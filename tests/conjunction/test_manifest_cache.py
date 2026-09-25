"""The manifest is built once per store change, not once per request.

Every edge asks for the hub's manifest every sync cycle (2 s by default).
Building it means a summary for every stored event, past ones included,
so it is cached against the store's version, which changes exactly when a
stored CDM, event or hub summary does. Only "active" (TCA in the future)
depends on the clock, and it is applied on every request.

The oracle is a second service over the same store: it has no cache.
"""

import datetime as dt

import pytest

from sentinel.conjunction.exercise import generate
from sentinel.conjunction.service import ConjunctionService
from sentinel.conjunction.sync_adapter import ConjunctionRecords

from .conftest import EPOCH, make_service, run


def release(service: ConjunctionService) -> None:
    """Ingest every exercise CDM released by the service's clock that is not already held."""
    for item in generate(EPOCH):
        if item.release_at <= service.clock.now():
            run(service.ingest(item.kvn.encode(), "exercise", "EXERCISE"))


@pytest.fixture
def hub():
    hub = make_service("hub")
    release(hub)
    return hub


def uncached(service: ConjunctionService) -> list[dict]:
    return ConjunctionService(service.store, service.bus, service.clock, node_id=service.node_id).manifest()


def summaries_built(service: ConjunctionService, monkeypatch) -> list[str]:
    built: list[str] = []
    original = service.event_summary

    def counted(event_id: str) -> dict:
        built.append(event_id)
        return original(event_id)

    monkeypatch.setattr(service, "event_summary", counted)
    return built


def test_a_second_request_with_no_store_change_builds_no_summary(hub, monkeypatch):
    first = hub.manifest()
    built = summaries_built(hub, monkeypatch)
    assert hub.manifest() == first == uncached(hub)
    assert built == []


def test_a_new_cdm_is_offered_on_the_next_request(hub, monkeypatch):
    before = hub.manifest()
    hub.clock.advance(3600)  # the scenario's later updates are released
    release(hub)
    built = summaries_built(hub, monkeypatch)
    after = hub.manifest()
    assert after != before
    assert after == uncached(hub)
    assert built, "the store changed, so the manifest was rebuilt"


def test_an_event_leaves_the_manifest_when_its_tca_passes_without_a_rebuild(hub, monkeypatch):
    offered = hub.manifest()
    soonest = min(offered, key=lambda compact: compact["t"])
    hub.clock.advance((dt.datetime.fromtimestamp(soonest["t"] + 1, dt.UTC) - hub.clock.now()).total_seconds())
    built = summaries_built(hub, monkeypatch)
    after = hub.manifest()
    assert soonest["e"] not in {compact["e"] for compact in after}
    assert after == [compact for compact in offered if compact["e"] != soonest["e"]] == uncached(hub)
    assert built == []


def test_an_event_this_node_holds_from_a_hub_is_no_longer_offered(hub):
    """A hub summary stored for an event changes its verification, so it is no longer this node's to offer."""
    edge = make_service("alpha")
    offered = hub.manifest()
    for compact in offered:
        row = hub.store.cdm_by_prefix(compact["c"][-1][0])
        run(edge.ingest(row.raw, "exercise", "EXERCISE", event_id=compact["e"]))
    assert len(edge.manifest()) == len(offered)

    ConjunctionRecords(edge).put_summaries(offered[:1], "hub")
    assert offered[0]["e"] not in {compact["e"] for compact in edge.manifest()}
    assert edge.manifest() == uncached(edge)


def test_the_manifest_is_in_triage_order(hub):
    active = [s["event_id"] for s in hub.list_events("active") if s["verification"] == "LOCAL"]
    assert [compact["e"] for compact in hub.manifest()] == active


def test_the_store_version_moves_with_what_views_are_built_from_and_nothing_else(hub):
    version = hub.store.version
    event_id = hub.list_events("active")[0]["event_id"]
    latest = hub.store.cdms_for_event(event_id)[-1]

    hub.store.put_assessment(latest.sha256, "another-engine", {"method": "REFUSED"})
    hub.store.quarantine("0" * 64, b"junk", "PARSE_ERROR", "not a CDM", "test")
    hub.store.add_cdm(latest)  # already held: ignored
    assert hub.store.version == version

    hub.store.put_remote_summary(event_id, {"e": event_id}, "hub", "2026-09-23T12:00:00+00:00")
    assert hub.store.version > version
