"""The LIMITED scenario reports repeated runs, never one.

One run of a real two-node cluster over a shaped link is one sample. Two
races once decided which mode got the better link: whether the element
sets crossed before the link was shaped, and whether NATS compressed the
hub's side of the leaf (s2_auto chose from a round trip measured before
shaping). A single run printed whichever came up as the result. So each
mode runs N times, the report states the median and the range, and the
scenario refuses to compare runs whose link was not the one intended.
"""

import pytest

from harness.cluster import preset_toxics, toxic_spec
from harness.stats import describe, link_mismatches, run_order, speedup, spread, summarize
from sentinel.linkstate.toxiproxy import PRESETS

LIMITED_TOXICS = [
    {"name": "bw_down", "type": "bandwidth", "stream": "downstream", "toxicity": 1.0, "attributes": {"rate": 1}},
    {"name": "latency_down", "type": "latency", "stream": "downstream", "toxicity": 1.0,
     "attributes": {"latency": 600, "jitter": 100}},
]
BEST = {"hub": "s2_best", "edge": "s2_best"}
LIMITED_LINK = {"toxics": LIMITED_TOXICS, "compression": BEST}


def a_run(mode: str, summaries: float, urgent: float, verified: float, **extra) -> dict:
    return {
        "mode": mode,
        "times_s": {"all_summaries": summaries, "most_urgent_full": urgent, "all_latest_verified": verified,
                    "all_records": 120.0},
        "link_up_s": 11.0,
        "records_fetched": 51,
        "record_bytes": 79_996,
        "rate_estimate_bytes_per_s": 1750,
        "link": {"start": LIMITED_LINK, "end": LIMITED_LINK},
        **extra,
    }


def test_spread_is_the_median_and_the_range():
    assert spread([3.0, 1.0, 2.0]) == {"median": 2.0, "min": 1.0, "max": 3.0, "n": 3}


def test_the_median_of_an_even_count_is_the_middle_pair_averaged():
    assert spread([1.0, 2.0, 3.0, 10.0])["median"] == 2.5


def test_no_measurements_is_an_error_not_a_zero():
    with pytest.raises(ValueError, match="no measurements"):
        spread([])


def test_summarize_spreads_every_time_and_counter_over_the_runs():
    runs = [a_run("edf", 6.0, 5.0, 30.0), a_run("edf", 7.0, 4.0, 35.0), a_run("edf", 6.5, 9.0, 31.0)]
    summary = summarize(runs)
    assert summary["most_urgent_full"] == {"median": 5.0, "min": 4.0, "max": 9.0, "n": 3}
    assert summary["all_summaries"]["median"] == 6.5
    assert summary["all_latest_verified"]["median"] == 31.0
    assert summary["records_fetched"] == {"median": 51, "min": 51, "max": 51, "n": 3}
    assert set(summary) == {
        "all_summaries", "most_urgent_full", "all_latest_verified", "all_records",
        "link_up_s", "records_fetched", "record_bytes", "rate_estimate_bytes_per_s",
    }


def test_speedup_is_the_ratio_of_the_medians_not_of_one_lucky_pair():
    edf = summarize([a_run("edf", 6, 5.0, 30), a_run("edf", 6, 4.0, 30), a_run("edf", 6, 50.0, 30)])
    fifo = summarize([a_run("fifo", 6, 100.0, 130), a_run("fifo", 6, 90.0, 130), a_run("fifo", 6, 10.0, 130)])
    assert speedup(edf, fifo) == 18.0      # 90 / 5; the best single pair would claim 25x


def test_modes_alternate_which_goes_first_so_neither_always_runs_second():
    assert run_order(3) == ["edf", "fifo", "fifo", "edf", "edf", "fifo"]
    assert run_order(1) == ["edf", "fifo"]


def test_runs_on_the_intended_link_raise_no_mismatch():
    runs = [a_run("edf", 6, 5, 30), a_run("fifo", 6, 90, 130)]
    assert link_mismatches(runs, LIMITED_LINK) == []


def test_a_run_whose_toxics_differed_at_the_start_or_end_is_named():
    faster = {"toxics": [{**LIMITED_TOXICS[0], "attributes": {"rate": 32}}, LIMITED_TOXICS[1]], "compression": BEST}
    unshaped = {"toxics": [], "compression": BEST}
    runs = [
        a_run("edf", 6, 5, 30),
        a_run("fifo", 6, 90, 130, link={"start": LIMITED_LINK, "end": faster}),
        a_run("edf", 6, 5, 30, link={"start": unshaped, "end": LIMITED_LINK}),
    ]
    assert link_mismatches(runs, LIMITED_LINK) == ["run 2 (fifo) at end", "run 3 (edf) at start"]


def test_a_run_whose_hub_did_not_compress_ran_on_a_different_link():
    """Same toxics, but 5 kB CDMs cross uncompressed: about 2.4 times the time each."""
    uncompressed = {"toxics": LIMITED_TOXICS, "compression": {"hub": "s2_uncompressed", "edge": "s2_best"}}
    runs = [a_run("edf", 6, 12, 180, link={"start": uncompressed, "end": uncompressed})]
    assert link_mismatches(runs, LIMITED_LINK) == ["run 1 (edf) at start", "run 1 (edf) at end"]


def test_toxic_order_does_not_matter_but_every_field_does():
    reordered = {"toxics": list(reversed(LIMITED_TOXICS)), "compression": BEST}
    assert link_mismatches([a_run("edf", 6, 5, 30, link={"start": reordered, "end": reordered})], LIMITED_LINK) == []
    half = {"toxics": [{**LIMITED_TOXICS[0], "toxicity": 0.5}, LIMITED_TOXICS[1]], "compression": BEST}
    assert link_mismatches([a_run("edf", 6, 5, 30, link={"start": half, "end": half})], LIMITED_LINK) == [
        "run 1 (edf) at start", "run 1 (edf) at end",
    ]


def test_toxiproxys_report_of_a_toxic_compares_equal_to_the_preset_that_set_it():
    reported = {"name": "bw_down", "type": "bandwidth", "stream": "downstream", "toxicity": 1, "attributes": {"rate": 1}}
    preset = {"name": "bw_down", "type": "bandwidth", "stream": "downstream", "attributes": {"rate": 1}}
    assert toxic_spec(reported) == toxic_spec(preset)
    assert toxic_spec({**reported, "attributes": {"rate": 32}}) != toxic_spec(preset)


def test_a_spread_reads_as_the_median_then_the_range():
    assert describe({"median": 9.0, "min": 8.5, "max": 12.3, "n": 5}) == "9.0 s (8.5–12.3)"
    assert describe({"median": 1750, "min": 1702, "max": 1811, "n": 5}, "B/s", 0) == "1,750 B/s (1,702–1,811)"


def test_a_spread_every_run_agreed_on_reads_as_one_value():
    assert describe({"median": 51, "min": 51, "max": 51, "n": 5}, "records", 0) == "51 records"


def test_the_expected_link_is_the_preset_the_harness_applies():
    assert preset_toxics("LIMITED") == [toxic_spec(t) for t in PRESETS["LIMITED"]]
    assert {t["name"] for t in preset_toxics("LIMITED")} == {"latency_down", "latency_up", "bw_down", "bw_up"}
