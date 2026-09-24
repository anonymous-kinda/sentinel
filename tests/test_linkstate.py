"""The link state is measured, and a link that returns is measured afresh."""

import time

from sentinel.linkstate import LinkMonitor, LinkState


def test_states_follow_measurements():
    m = LinkMonitor(denied_after_s=0.05)
    assert m.state is LinkState.UNKNOWN
    m.observe_success(0.01, 50_000, 0.01)
    assert m.state is LinkState.CONNECTED
    m.observe_success(1.5)
    assert m.state is LinkState.CONNECTED, "one slow round trip is smoothed, not a verdict"
    for _ in range(4):
        m.observe_success(1.5)
    assert m.state is LinkState.DEGRADED
    m.observe_failure()
    time.sleep(0.06)
    assert m.state is LinkState.DENIED


def test_recovery_forgets_the_fast_link_that_went_away():
    m = LinkMonitor(denied_after_s=0.05)
    m.observe_success(0.002, 5_000_000, 1.0)          # fast LAN-class link
    m.observe_failure()
    time.sleep(0.06)
    assert m.state is LinkState.DENIED
    m.observe_success(1.3, 6_000, 6.0)                # back, over a thin link
    assert m.rate_bytes_per_s == 1000.0
    assert m.state is LinkState.LIMITED


def test_eta_uses_measured_rate():
    m = LinkMonitor()
    assert m.eta_s(10_000) is None
    m.observe_success(0.5, 4_000, 4.0)
    assert round(m.eta_s(10_000), 1) == 10.5
