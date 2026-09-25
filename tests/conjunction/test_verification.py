"""VERIFIED means the edge re-assessed the same CDM and reached what the hub asserted.

ADR-008: an event stays HUB-ASSERTED until the edge's own assessment of the
fetched CDM passes the comparison with the hub's summary; any disagreement
is MISMATCH ("same CDM, different result"). The inputs hash alone cannot
say that: it covers only the CDM's inputs, so a hub on another engine
version or configuration (`default_radius_m` is not in it), or with a bug,
could assert RED at Pc 8.6e-4 while the edge refused, and still be VERIFIED.

Each test takes the hub's summary across the wire (CBOR) into the edge, as
the sync agent does, and then hands the edge the CDM the hub fetched out.
"""

import logging

import pytest

from sentinel.conjunction.sync_adapter import ConjunctionRecords
from sentinel.crdt import codec
from sentinel.risk.types import AssessmentConfig

from .conftest import make_service, real_kvn, run, without_hbr

LOGGER = "sentinel.conjunction.sync_adapter"


def hub_assertion(raw: bytes, config: AssessmentConfig | None = None) -> dict:
    """The one summary a hub offers for this CDM, as an edge decodes it."""
    hub = make_service("hub", config)
    run(hub.ingest(raw, "api-upload", "REAL"))
    (compact,) = codec.decode(codec.encode(hub.manifest()))
    return compact


def fetched_at_edge(asserted: dict, raw: bytes, config: AssessmentConfig | None = None):
    edge = make_service("alpha", config)
    records = ConjunctionRecords(edge)
    records.put_summaries([asserted], "hub")
    arrival = run(records.ingest(raw, "sync", "REAL", asserted["e"]))
    (listed,) = edge.list_events("active")
    return edge, arrival, listed


def test_the_same_engine_on_the_same_cdm_is_verified():
    raw = real_kvn().encode()
    _, arrival, listed = fetched_at_edge(hub_assertion(raw), raw)
    assert arrival["verification"] == listed["verification"] == "VERIFIED"


def test_a_hub_that_concludes_otherwise_from_the_same_inputs_is_a_mismatch():
    """The hub defaults a 10 m radius the CDM does not give; the edge, configured without one, refuses."""
    raw = without_hbr(real_kvn()).encode()
    asserted = hub_assertion(raw, AssessmentConfig(default_radius_m=10.0))
    edge, arrival, listed = fetched_at_edge(asserted, raw)

    mine = listed["assessment"]
    assert mine["inputs_hash"][:16] == asserted["h"], "the same inputs on both nodes"
    assert (asserted["b"], asserted["r"]) == ("R", None)
    assert (listed["band"], mine["refusal_reason"]) == ("UNASSESSED", "NO_HBR")
    assert arrival["verification"] == listed["verification"] == "MISMATCH"
    assert edge.event_detail(asserted["e"])["summary"]["verification"] == "MISMATCH"


def _other_band(band):
    return "G" if band != "G" else "R"


# Each result field the summary carries, asserted otherwise by the hub.
ASSERTED_OTHERWISE = {
    "inputs hash": ("h", lambda h: "0" * 16),
    "method (refused)": ("r", lambda r: "NO_HBR"),
    "band": ("b", _other_band),
    "worst-case band": ("w", lambda w: None),
    "Pc, one step of its rounding": ("pc", lambda pc: round(pc + 0.001, 3)),
    "max Pc": ("px", lambda px: round(px - 0.5, 3)),
    "dilution flag": ("d", lambda d: not d),
    "miss distance": ("md", lambda md: md + 0.1),
    "relative speed": ("rs", lambda rs: rs - 0.1),
}


@pytest.mark.parametrize("field", ASSERTED_OTHERWISE)
def test_any_result_the_hub_asserted_otherwise_is_a_mismatch(field):
    raw = real_kvn().encode()
    asserted = hub_assertion(raw)
    key, change = ASSERTED_OTHERWISE[field]
    asserted[key] = change(asserted[key])
    _, arrival, listed = fetched_at_edge(asserted, raw)
    assert arrival["verification"] == listed["verification"] == "MISMATCH"


def test_a_mismatch_on_arrival_is_logged_with_the_fields_that_differ(caplog):
    raw = without_hbr(real_kvn()).encode()
    asserted = hub_assertion(raw, AssessmentConfig(default_radius_m=10.0))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        fetched_at_edge(asserted, raw)
    (record,) = [r for r in caplog.records if r.getMessage() == "Hub assertion not reproduced"]
    assert record.fields["event_id"] == asserted["e"]
    assert record.fields["origin"] == "hub"
    assert set(record.fields["fields"]) == {"r", "b", "w", "pc", "px", "d"}


def test_nothing_is_logged_when_the_edge_verifies(caplog):
    raw = real_kvn().encode()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        fetched_at_edge(hub_assertion(raw), raw)
    assert not [r for r in caplog.records if r.getMessage() == "Hub assertion not reproduced"]
