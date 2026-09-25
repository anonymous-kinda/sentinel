"""The harness CLI hands each scenario its own options, and only its own.

CI runs LIMITED with fewer repeats than `make ddil` (harness.yml); the
report states how many runs each median came from.
"""

import pytest

from harness.run import options_for, parse
from harness.scenarios import LIMITED_RUNS


def test_limited_runs_reach_the_limited_scenario_only():
    args = parse(["limited", "degraded", "--limited-runs", "3"])
    assert options_for("limited", args) == {"runs_per_mode": 3}
    assert options_for("degraded", args) == {}


def test_the_defaults_are_the_full_local_measurement():
    args = parse(["all"])
    assert options_for("limited", args) == {"runs_per_mode": LIMITED_RUNS}
    assert options_for("denied", args) == {"denial_s": 20.0}


def test_a_median_needs_at_least_one_run():
    with pytest.raises(SystemExit):
        parse(["limited", "--limited-runs", "0"])
