"""docs/ddil-results.md is written from all six scenarios or not at all.

The report renders harness/results/. Run one scenario on a fresh clone and
that directory holds one result, so a report written from it would drop
the other five from a committed document. It refuses instead, and names
what is missing; `make opsec` runs its scenario and leaves the report be.
"""

import json
import pathlib

import pytest

from harness import report
from harness.stats import speedup, summarize
from tests.makefile import dry_run

COMMITTED = "# DDIL test results\n\nevery scenario, from a complete run\n"


def limited_run(mode: str, urgent: float, load: float) -> dict:
    """One LIMITED run as harness.scenarios records it."""
    return {
        "mode": mode, "load_1min": {"start": load, "end": load + 0.5}, "link_up_s": 11.0,
        "times_s": {"all_summaries": 6.0, "most_urgent_full": urgent, "all_latest_verified": urgent + 30,
                    "all_records": 150.0},
        "records_fetched": 51, "record_bytes": 79_996, "cdms": 13, "cdm_bytes": 64_058, "element_sets": 38,
        "rate_estimate_bytes_per_s": 1750, "link_state": "LIMITED",
    }


def limited_metrics() -> dict:
    runs = [limited_run("edf", 9.0, 2.0), limited_run("fifo", 130.0, 2.1), limited_run("fifo", 120.0, 3.4),
            limited_run("edf", 8.5, 1.9)]
    edf, fifo = (summarize([run for run in runs if run["mode"] == mode]) for mode in ("edf", "fifo"))
    return {"runs_per_mode": 2, "edf": edf, "fifo": fifo, "most_urgent_speedup": speedup(edf, fifo), "runs": runs}


def result(name: str) -> dict:
    metrics = limited_metrics() if name == "limited" else {"runs": 1}
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


def report_lines(target: str) -> list[str]:
    return [line for line in dry_run(target) if "harness.report" in line]


def test_make_opsec_rewrites_the_report_only_from_a_complete_set():
    assert report_lines("opsec") and all("--if-complete" in line for line in report_lines("opsec"))


def test_make_ddil_insists_on_a_complete_report():
    assert report_lines("ddil") and not any("--if-complete" in line for line in report_lines("ddil"))


# ------------------------------------------------------------ the LIMITED section
def limited_section() -> str:
    return report.render({name: result(name) for name in report.ORDER}).split("## LIMITED")[1].split("## ")[0]


def test_limited_states_medians_and_ranges_and_how_many_runs_they_come_from():
    section = limited_section()
    assert "median (range) of 2 runs per mode" in section
    assert "| **most urgent event's full CDM** | **8.8 s (8.5–9.0)** | **125.0 s (120.0–130.0)** |" in section
    assert "**14.3x sooner**" in section


def test_limited_states_the_workload_both_modes_moved():
    assert "same 51 records (13 CDMs, 64,058 bytes of KVN, and 38 element sets; 79,996 bytes in all)" in limited_section()


def test_limited_says_the_rate_estimate_is_not_the_link():
    section = limited_section()
    assert "| edge's rate estimate at the end | 1,750 B/s | 1,750 B/s |" in section
    assert "not the link's capacity" in " ".join(section.split())


def test_limited_lists_every_run_in_the_order_run_with_the_load_it_ran_under():
    rows = [line for line in limited_section().splitlines() if line.startswith("| ") and line.split("|")[1].strip().isdigit()]
    assert [row.split("|")[2].strip() for row in rows] == ["EDF", "FIFO", "FIFO", "EDF"]
    assert rows[2].split("|")[3].strip() == "3.4 → 3.9"
