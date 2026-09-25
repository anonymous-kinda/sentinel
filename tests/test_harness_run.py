"""The harness CLI hands each scenario its own options, and only its own.

CI runs LIMITED with fewer repeats than `make ddil` (harness.yml); the
report states how many runs each median came from.
"""

import json

import pytest

from harness import run
from harness.run import options_for, parse
from harness.scenarios import LIMITED_RUNS, Result


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


def passing(name: str):
    def scenario(**options) -> Result:
        result = Result(name.upper())
        result.check("it held", True)
        return result

    return scenario


def test_every_result_one_invocation_writes_names_one_run_and_the_next_invocation_another(tmp_path, monkeypatch):
    """The report takes all six results from one run; each result says which."""
    monkeypatch.setattr(run, "SCENARIOS", {name: passing(name) for name in ("denied", "opsec")})
    monkeypatch.setattr(run, "RESULTS", tmp_path)

    def run_ids() -> dict[str, str]:
        return {path.stem: json.loads(path.read_text()).get("run_id") for path in tmp_path.glob("*.json")}

    assert run.main(["all"]) == 0
    first = run_ids()
    assert first["denied"] and first["denied"] == first["opsec"]

    assert run.main(["opsec"]) == 0
    second = run_ids()
    assert second["denied"] == first["denied"] and second["opsec"] != first["opsec"]
