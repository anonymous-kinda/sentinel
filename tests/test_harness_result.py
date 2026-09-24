"""A scenario result says what load the machine carried while it ran.

Latency checks (DENIED's console p95) move with CPU contention from other
work on the machine, so every result records the 1-minute load average at
its start and end, and the report shows it beside the scenario.
"""

from harness.scenarios import Result


def test_a_result_records_the_load_at_its_start_and_end(monkeypatch):
    loads = iter([(1.5, 1.0, 0.5), (2.25, 1.2, 0.6)])
    monkeypatch.setattr("harness.scenarios.os.getloadavg", lambda: next(loads))
    result = Result("DENIED")
    assert result.to_dict()["load_1min"] == {"start": 1.5, "end": 2.25}
