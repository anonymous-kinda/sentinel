"""Hub and edge in one process over a shared in-process bus.

The same code paths run over NATS leaf nodes in the DDIL harness; here the
transport is trivial so the behaviour under test is the protocol itself:
summaries first, earliest-deadline-first pulls, verification, operator data
merging both ways, and REVIEW REQUIRED when a decision's CDM is superseded.
"""

from sentinel.bus import InProcessBus
from sentinel.conjunction.exercise import generate
from sentinel.conjunction.summaries import SUMMARY_MAX_BYTES, summary_only
from sentinel.crdt import codec
from sentinel.linkstate import LinkMonitor
from sentinel.sync import SyncAgent
from sentinel.triage import PriorityClass

from .conftest import EPOCH, run


def test_summaries_are_small_enough_to_send_first(pair):
    hub, *_ = pair
    for compact in hub.conj.manifest():
        size = len(codec.encode(summary_only(compact)))
        assert size <= SUMMARY_MAX_BYTES, f"{compact['e']}: summary is {size} bytes"


def test_edge_sees_every_event_as_hub_asserted_before_any_cdm_arrives(pair):
    hub, edge, agent, _ = pair
    manifest = run(agent.fetch_manifest())
    agent.apply_manifest(manifest)
    listed = edge.conj.list_events("active")
    assert {e["event_id"] for e in listed} == {e["event_id"] for e in hub.conj.list_events("active")}
    assert {e["verification"] for e in listed} == {"HUB_ASSERTED"}
    assert all(e["voice"] for e in listed)


def test_latest_records_are_queued_before_history_and_by_deadline(pair):
    _, _, agent, _ = pair
    agent.apply_manifest(run(agent.fetch_manifest()))
    classes = [i.key.klass for i in agent.queue]
    assert classes == sorted(classes), "class order: urgent, routine, then bulk history"
    assert classes[-1] is PriorityClass.P4_BULK
    urgent = [i for i in agent.queue if i.key.klass is PriorityClass.P1_URGENT]
    deadlines = [i.key.deadline for i in urgent]
    assert deadlines == sorted(deadlines), "earliest deadline first within a class"


def test_fifo_baseline_orders_by_arrival_only(pair):
    hub, edge, _, clock = pair
    fifo = SyncAgent(InProcessBus(), edge.records, edge.ops, clock, "alpha", "hub", LinkMonitor(), mode="fifo")
    fifo.apply_manifest(hub.conj.manifest())
    created = [i.created for i in fifo.queue]
    assert created == sorted(created)


def test_full_sync_verifies_every_event_against_the_hub(pair):
    hub, edge, agent, _ = pair
    run(agent.cycle())
    listed = edge.conj.list_events("active")
    assert {e["verification"] for e in listed} == {"VERIFIED"}
    for e in listed:
        assert e["event_id"] in {h["event_id"] for h in hub.conj.list_events("active")}
    assert all(a["hash_ok"] for a in agent.arrivals)


def test_operator_data_merges_both_ways_and_conflicts_are_kept(pair):
    hub, edge, agent, _ = pair
    run(agent.cycle())
    event_id = edge.conj.list_events("active")[0]["event_id"]

    run(edge.ops.annotate(event_id, "triage_status", "MANEUVER_PLANNING", "maj.ortiz@alpha"))
    run(hub.ops.annotate(event_id, "triage_status", "WATCH", "capt.lee@hub"))
    run(edge.ops.append(event_id, "DECISION", {"decision": "MANEUVER"}, "maj.ortiz@alpha"))
    run(agent.exchange_ops())

    for node in (hub, edge):
        status = node.ops.annotations(event_id)["triage_status"]
        assert status["conflict"] is True
        assert {v["v"] for v in status["values"]} == {"MANEUVER_PLANNING", "WATCH"}
    assert hub.ops.digest()["log"] == edge.ops.digest()["log"]
    assert hub.ops.entries(event_id)[0]["signature_valid"]


def test_decision_becomes_review_required_when_its_cdm_is_superseded(pair):
    hub, edge, agent, clock = pair
    run(agent.cycle())
    dil = next(e for e in edge.conj.list_events("active") if e["secondary"]["id"] == "99412")
    run(edge.ops.append(dil["event_id"], "DECISION", {"decision": "MONITOR"}, "maj.ortiz@alpha"))
    assert edge.ops.entries(dil["event_id"])[-1]["review_required"] is False

    clock.advance(3600)  # the scenario's later updates are released
    for item in generate(EPOCH):
        if item.release_at <= clock.now():
            run(hub.conj.ingest(item.kvn.encode(), "exercise", "EXERCISE"))
    run(agent.cycle())
    assert edge.ops.entries(dil["event_id"])[-1]["review_required"] is True
