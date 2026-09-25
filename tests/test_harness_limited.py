"""When a LIMITED run reaches each of the moments it times.

The scenario looks at the edge every half second: its events (conjunction
summaries and their verification) and its sync status (the want-queue).
From one look it decides which milestones are reached. "Every record
delivered" is how a run shows it moved the whole backlog, so both modes
can be held to the same bytes.
"""

from harness.scenarios import limited_milestones

HUB = {"EV-1": {"event_id": "EV-1"}, "EV-2": {"event_id": "EV-2"}}


def edge(**verification: str) -> dict:
    return {event_id: {"event_id": event_id, "verification": v} for event_id, v in verification.items()}


def status(*queue: str, cycled: bool = True) -> dict:
    return {"queue": [{"status": s} for s in queue], "last_cycle": {"at": "2026-09-24T06:01:00+00:00"} if cycled else {}}


def reached(edge_events: dict, sync: dict) -> set[str]:
    return {name for name, done in limited_milestones(HUB, "EV-1", edge_events, sync).items() if done}


def test_before_the_first_manifest_nothing_is_reached_though_the_queue_is_empty():
    assert reached({}, status(cycled=False)) == set()


def test_every_summary_is_visible_while_every_record_is_still_queued():
    assert reached(edge(**{"EV-1": "HUB-ASSERTED", "EV-2": "HUB-ASSERTED"}), status("QUEUED", "QUEUED")) == {"all_summaries"}


def test_the_most_urgent_event_verified_first():
    assert reached(edge(**{"EV-1": "VERIFIED", "EV-2": "HUB-ASSERTED"}), status("ARRIVED", "QUEUED")) == {
        "all_summaries", "most_urgent_full",
    }


def test_every_event_verified_while_history_and_element_sets_still_queue():
    assert reached(edge(**{"EV-1": "VERIFIED", "EV-2": "VERIFIED"}), status("ARRIVED", "QUEUED")) == {
        "all_summaries", "most_urgent_full", "all_latest_verified",
    }


def test_every_record_delivered_once_nothing_in_the_queue_is_unfetched():
    verified = edge(**{"EV-1": "VERIFIED", "EV-2": "VERIFIED"})
    everything = {"all_summaries", "most_urgent_full", "all_latest_verified", "all_records"}
    assert reached(verified, status("ARRIVED", "ARRIVED")) == everything
    assert reached(verified, status()) == everything


def test_a_record_held_summary_only_settles_the_backlog_without_being_delivered():
    """Admission control may hold a record the link cannot deliver in time. The run
    ends there rather than waiting out its timeout; the records-moved check then
    shows that this run moved fewer records than the others."""
    verified = edge(**{"EV-1": "VERIFIED", "EV-2": "VERIFIED"})
    assert "all_records" in reached(verified, status("ARRIVED", "SUMMARY_ONLY"))
    assert "all_records" not in reached(verified, status("ARRIVED", "FETCHING"))
