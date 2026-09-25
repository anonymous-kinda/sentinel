"""An event holds one data class: a CDM of another class never joins it.

Reachable on any node that can write. POST /api/screening files each close
approach as a DERIVED CDM (ORIGINATOR SENTINEL-SCREENING, geometry only),
and POST /api/ingest/cdm admits any CDM, reclassified by its ORIGINATOR.
Both call ConjunctionService.ingest, as these tests do. A screening TCA from
SGP4 lands within a second or so of the precise TCA of a REAL CDM for the
same pair, well inside the 60 s grouping window, and it is created later.
Filed in the REAL event, it became the latest CDM: its NO_COVARIANCE
refusal replaced the real Pc in the summary, the band and `current_ref`.
"""

import pytest

from .conftest import edited, make_service, real_kvn, run, without_covariance

REAL_EVENT = "99001-99118-20260924T070000"
LATER = "2026-09-23T11:59:00.000"
OTHER_CLASS = {
    "DERIVED": lambda kvn: without_covariance(edited(kvn, ORIGINATOR="SENTINEL-SCREENING")),
    "EXERCISE": lambda kvn: edited(kvn, ORIGINATOR="SENTINEL-EXERCISE"),
}


@pytest.fixture
def service():
    service = make_service()
    admitted = run(service.ingest(real_kvn().encode(), "api-upload", "REAL"))
    assert admitted.event_id == REAL_EVENT
    return service


def later_cdm(make, tca: str) -> bytes:
    return make(edited(real_kvn(), CREATION_DATE=LATER, TCA=tca)).encode()


@pytest.mark.parametrize("data_class", OTHER_CLASS)
@pytest.mark.parametrize("tca", ["2026-09-24T07:00:00.000", "2026-09-24T07:00:00.400", "2026-09-24T07:00:30.000"])
def test_a_later_cdm_of_another_class_starts_its_own_event(service, data_class, tca):
    real = service.event_summary(REAL_EVENT)
    other = run(service.ingest(later_cdm(OTHER_CLASS[data_class], tca), "api-upload", "REAL"))

    assert other.status == "accepted"
    assert other.event_id != REAL_EVENT
    assert service.event_summary(other.event_id)["data_class"] == data_class
    after = service.event_summary(REAL_EVENT)
    assert after["data_class"] == "REAL"
    assert after["cdm_count"] == 1
    assert after["latest_cdm_sha256"] == real["latest_cdm_sha256"]
    assert (after["band"], after["assessment"]) == (real["band"], real["assessment"])
    assert service.current_ref(REAL_EVENT)["cdm_sha256"] == real["latest_cdm_sha256"]


def test_an_event_id_another_class_holds_gets_the_data_class_appended(service):
    derived = run(service.ingest(later_cdm(OTHER_CLASS["DERIVED"], "2026-09-24T07:00:00.400"), "api-screening", "DERIVED"))
    assert derived.event_id == f"{REAL_EVENT}-DERIVED"


def test_a_screening_cdm_keeps_its_refusal_in_its_own_event(service):
    derived = run(service.ingest(later_cdm(OTHER_CLASS["DERIVED"], "2026-09-24T07:00:00.000"), "api-screening", "DERIVED"))
    summary = service.event_summary(derived.event_id)
    assert summary["assessment"]["refusal_reason"] == "NO_COVARIANCE"
    assert service.event_summary(REAL_EVENT)["assessment"]["method"] == "FOSTER_ESTES_2D"
    assert {e["event_id"] for e in service.list_events("all")} == {REAL_EVENT, derived.event_id}


def test_a_real_cdm_does_not_join_a_screening_event_either():
    service = make_service()
    derived = run(service.ingest(later_cdm(OTHER_CLASS["DERIVED"], "2026-09-24T07:00:00.000"), "api-screening", "DERIVED"))
    real = run(service.ingest(real_kvn().encode(), "api-upload", "REAL"))
    assert real.event_id != derived.event_id
    assert service.event_summary(real.event_id)["assessment"]["method"] == "FOSTER_ESTES_2D"
    assert service.event_summary(derived.event_id)["assessment"]["refusal_reason"] == "NO_COVARIANCE"


def test_an_update_of_the_same_class_still_joins_the_event(service):
    update = run(service.ingest(edited(real_kvn(), CREATION_DATE=LATER, TCA="2026-09-24T07:00:00.400").encode(),
                                "api-upload", "REAL"))
    assert update.event_id == REAL_EVENT
    assert service.event_summary(REAL_EVENT)["cdm_count"] == 2
