"""What the edge says it fetched, counted without gaps or guesses.

`GET /api/sync` on an edge shows only the most recent arrivals, with a
running total. A scenario that counts fetched records from one late read
is silently wrong once more records arrive than the window shows. The
ledger reads the status as the scenario goes and keeps every arrival.
"""

from harness.ledger import SyncLedger


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


def test_a_ledger_started_mid_run_keeps_only_what_arrives_after_it_started():
    """DENIED counts the catch-up after a reconnect: more than the window, and nothing from before."""
    before = [arrival(f"EV-{n}") for n in range(20)]
    after = [arrival(f"omm:{n}") for n in range(70)]
    ledger = SyncLedger(after=sync_status(before)["arrivals_total"])
    for seen in (0, 30, 60, 70):
        ledger.record(sync_status(before + after[:seen]))
    assert ledger.arrivals == after
    assert ledger.unseen == 0


def test_ledgers_that_fetched_the_same_records_in_any_order_share_one_digest():
    """LIMITED's "same bytes": every run of either mode moved the identical records."""
    records = [arrival(f"omm:{n}") for n in range(5)] + [arrival("EV-1")]
    in_order, reversed_order, one_short = SyncLedger(), SyncLedger(), SyncLedger()
    in_order.record(sync_status(records))
    reversed_order.record(sync_status(list(reversed(records))))
    one_short.record(sync_status(records[:-1]))
    assert in_order.digest() == reversed_order.digest()
    assert in_order.digest() != one_short.digest()
