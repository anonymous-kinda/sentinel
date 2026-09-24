"""The DDIL harness must never hand two processes the same port.

A collision surfaced as the edge's health check answered by Toxiproxy's API
(HTTP 404) - a flaky failure in the RECOVERY scenario.
"""

import pytest

from harness.cluster import allocate_ports


@pytest.mark.enable_socket  # binds loopback ports only; no network access
def test_allocated_ports_are_distinct_and_named():
    names = [f"p{i}" for i in range(40)]
    ports = allocate_ports(names)
    assert set(ports) == set(names)
    assert len(set(ports.values())) == len(names)
