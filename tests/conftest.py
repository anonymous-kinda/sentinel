"""Shared fixtures for the risk engine test ladder.

The geometry builder lives in sentinel.risk.synthetic so scripts and the
exercise generator can use it without importing from the test suite.
"""

import pytest

from sentinel.risk.synthetic import make_conjunction

__all__ = ["make_conjunction"]


@pytest.fixture
def nominal_conjunction():
    """A representative LEO conjunction: 100 m miss, 50 m sigma, 10 m HBR."""
    return make_conjunction(miss_m=100.0, sigma_m=50.0, radius_m=5.0)
