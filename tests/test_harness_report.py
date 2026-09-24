"""docs/ddil-results.md is written from all six scenarios or not at all.

The report renders harness/results/. Run one scenario on a fresh clone and
that directory holds one result, so a report written from it would drop
the other five from a committed document. It refuses instead, and names
what is missing; `make opsec` runs its scenario and leaves the report be.
"""

import json
import pathlib
import subprocess

import pytest

from harness import report

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMMITTED = "# DDIL test results\n\nevery scenario, from a complete run\n"


def result(name: str) -> dict:
    metrics = {"runs": 1}
    if name == "limited":
        run = {
            "times_s": {"all_summaries": 1.0, "most_urgent_full": 2.0, "all_latest_verified": 3.0},
            "measured_rate_bytes_per_s": 1000, "records": 10, "record_bytes": 10_000,
        }
        metrics = {"edf": run, "fifo": run, "most_urgent_speedup": 1.0}
    return {
        "scenario": name.upper(), "passed": True, "notes": [], "metrics": metrics,
        "assertions": [{"name": "it held", "passed": True, "detail": ""}],
        "ran_at": "2026-09-24T06:00:00+00:00",
    }


@pytest.fixture
def harness_dirs(tmp_path, monkeypatch):
    results, out = tmp_path / "results", tmp_path / "ddil-results.md"
    results.mkdir()
    out.write_text(COMMITTED)
    monkeypatch.setattr(report, "RESULTS", results)
    monkeypatch.setattr(report, "OUT", out)
    return results, out


def write_results(results: pathlib.Path, names) -> None:
    for name in names:
        (results / f"{name}.json").write_text(json.dumps(result(name)))


def test_the_report_waits_for_every_scenario_the_harness_runs():
    assert report.ORDER == ["denied", "limited", "intermittent", "degraded", "recovery", "opsec"]


def test_one_result_does_not_overwrite_the_report(harness_dirs, capsys):
    results, out = harness_dirs
    write_results(results, ["opsec"])
    assert report.main([]) == 1
    assert out.read_text() == COMMITTED
    assert "no result for denied, limited, intermittent, degraded, recovery" in capsys.readouterr().err


def test_if_complete_skips_an_incomplete_report_without_failing(harness_dirs, capsys):
    results, out = harness_dirs
    write_results(results, ["opsec"])
    assert report.main(["--if-complete"]) == 0
    assert out.read_text() == COMMITTED
    assert "no result for denied, limited, intermittent, degraded, recovery" in capsys.readouterr().err


def test_every_result_present_writes_every_scenario(harness_dirs):
    results, out = harness_dirs
    write_results(results, report.ORDER)
    assert report.main([]) == 0
    text = out.read_text()
    assert [f"## {name.upper()}" in text for name in report.ORDER] == [True] * len(report.ORDER)


def recipe(target: str) -> list[str]:
    """What `make <target>` would run, without running it."""
    done = subprocess.run(["make", "-n", "--no-print-directory", target], cwd=ROOT,
                          capture_output=True, text=True, check=True)
    return done.stdout.splitlines()


def report_lines(target: str) -> list[str]:
    return [line for line in recipe(target) if "harness.report" in line]


def test_make_opsec_rewrites_the_report_only_from_a_complete_set():
    assert report_lines("opsec") and all("--if-complete" in line for line in report_lines("opsec"))


def test_make_ddil_insists_on_a_complete_report():
    assert report_lines("ddil") and not any("--if-complete" in line for line in report_lines("ddil"))
