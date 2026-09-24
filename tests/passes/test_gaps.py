"""Gaps: when no catalogued imager can observe the unit, and the next one
long enough to act in."""

import datetime as dt

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sentinel.passes.gaps import GAP_LABEL, Gap, next_unobserved, unobserved_gaps
from sentinel.passes.model import PassWindow

T0 = dt.datetime(2026, 9, 24, 6, 0, tzinfo=dt.UTC)
END = T0 + dt.timedelta(hours=6)
PAD = dt.timedelta(seconds=60)          # element_pad_s at age 0


def minutes(m: float) -> dt.datetime:
    return T0 + dt.timedelta(minutes=m)


def window(rise_min, set_min, sensor="SAR", sunlit=None, age_days=0.0, norad_id=36605):
    rise, set_ = minutes(rise_min), minutes(set_min)
    return PassWindow(
        norad_id=norad_id, name="TEST", sensor=sensor, rise=rise, culmination=rise + (set_ - rise) / 2, set=set_,
        max_elevation_deg=45.0, mask_elevation_deg=20.0, element_age_days=age_days,
        sunlit=sunlit if sensor == "EO" else None, provider="test",
    )


def spans(gaps):
    return [(g.start, g.end) for g in gaps]


def test_with_no_windows_the_whole_interval_is_one_gap():
    (gap,) = unobserved_gaps([], T0, END)
    assert (gap.start, gap.end, gap.low_confidence) == (T0, END, False)
    assert gap.label == GAP_LABEL == "not observed by catalogued imagers"
    assert gap.duration_s == 6 * 3600


def test_a_usable_window_splits_the_interval_at_its_padded_edges():
    gaps = unobserved_gaps([window(60, 70)], T0, END)
    assert spans(gaps) == [(T0, minutes(60) - PAD), (minutes(70) + PAD, END)]


def test_a_night_pass_of_an_optical_imager_observes_nothing():
    night = window(60, 70, sensor="EO", sunlit=False)
    day = window(120, 130, sensor="EO", sunlit=True)
    gaps = unobserved_gaps([night, day], T0, END)
    assert spans(gaps) == [(T0, minutes(120) - PAD), (minutes(130) + PAD, END)]


def test_overlapping_padded_windows_merge_into_one_observed_span():
    gaps = unobserved_gaps([window(60, 70), window(71, 80), window(75, 78)], T0, END)
    assert spans(gaps) == [(T0, minutes(60) - PAD), (minutes(80) + PAD, END)]


def test_windows_that_only_touch_leave_no_zero_length_gap():
    gaps = unobserved_gaps([window(60, 70), window(72, 80)], T0, END)
    assert spans(gaps) == [(T0, minutes(60) - PAD), (minutes(80) + PAD, END)]


def test_the_pad_grows_with_element_set_age():
    two_days = dt.timedelta(seconds=120)
    gaps = unobserved_gaps([window(60, 70, age_days=2.0)], T0, END)
    assert spans(gaps) == [(T0, minutes(60) - two_days), (minutes(70) + two_days, END)]


def test_windows_reaching_past_the_interval_are_clipped():
    gaps = unobserved_gaps([window(-10, 5), window(355, 400)], T0, END)
    assert spans(gaps) == [(minutes(5) + PAD, minutes(355) - PAD)]


def test_an_interval_covered_end_to_end_has_no_gap():
    assert unobserved_gaps([window(-10, 400)], T0, END) == []


def test_a_gap_bounded_by_a_stale_window_is_low_confidence():
    stale = window(60, 70, age_days=3.5)
    fresh = window(200, 210)
    before, after_stale, last = unobserved_gaps([stale, fresh], T0, END)
    assert before.low_confidence and after_stale.low_confidence
    assert not last.low_confidence


def test_a_stale_night_pass_inside_a_gap_makes_it_low_confidence():
    stale_night = window(100, 110, sensor="EO", sunlit=False, age_days=4.0)
    first, second = unobserved_gaps([window(60, 70), stale_night, window(200, 210)], T0, END)[:2]
    assert not first.low_confidence
    assert second.low_confidence


def test_a_stale_window_merged_away_from_the_gap_edge_does_not_taint_it():
    """Only windows that bound or overlap a gap decide its confidence."""
    stale_inside = window(62, 66, age_days=3.5)
    gaps = unobserved_gaps([window(60, 70), stale_inside], T0, END)
    assert [g.low_confidence for g in gaps] == [False, False]


@pytest.mark.parametrize(
    "start,end",
    [(T0.replace(tzinfo=None), END), (T0, END.replace(tzinfo=None)), (END, T0), (T0, T0)],
)
def test_a_naive_or_empty_interval_is_refused(start, end):
    with pytest.raises(ValueError, match="interval"):
        unobserved_gaps([], start, end)


window_spans = st.lists(
    st.tuples(st.integers(-30, 390), st.integers(1, 20), st.booleans(), st.floats(0.0, 5.0)), max_size=12
)


@settings(max_examples=200, deadline=None)
@given(window_spans)
def test_gaps_are_exactly_the_time_no_padded_usable_window_covers(specs):
    windows = [window(r, r + d, sensor="EO", sunlit=lit, age_days=age) for r, d, lit, age in specs]
    gaps = unobserved_gaps(windows, T0, END)
    covered = [w.padded for w in windows if w.usable]
    for g in gaps:
        assert T0 <= g.start < g.end <= END
        assert not any(a < g.end and g.start < b for a, b in covered)
    for earlier, later in zip(gaps, gaps[1:]):
        assert earlier.end < later.start
    for second in range(0, int((END - T0).total_seconds()) + 1, 60):
        instant = T0 + dt.timedelta(seconds=second)
        in_gap = any(g.start <= instant <= g.end for g in gaps)
        in_window = any(a <= instant <= b for a, b in covered)
        assert in_gap or in_window


# ---------------------------------------------------------------- next gap

GAPS = [
    Gap(minutes(0), minutes(10), low_confidence=False),
    Gap(minutes(20), minutes(25), low_confidence=False),
    Gap(minutes(40), minutes(100), low_confidence=True),
]


def test_the_next_gap_is_the_first_long_enough_to_act_in():
    gap = next_unobserved(GAPS, now=minutes(0), min_duration=dt.timedelta(minutes=30))
    assert (gap.start, gap.end) == (minutes(40), minutes(100))
    assert gap.low_confidence and gap.label == GAP_LABEL


def test_a_gap_in_progress_counts_from_now():
    gap = next_unobserved(GAPS, now=minutes(5), min_duration=dt.timedelta(minutes=5))
    assert (gap.start, gap.end) == (minutes(5), minutes(10))
    later = next_unobserved(GAPS, now=minutes(6), min_duration=dt.timedelta(minutes=5))
    assert (later.start, later.end) == (minutes(20), minutes(25)), "4 min left of the first gap is too short"


def test_gaps_already_over_are_ignored():
    gap = next_unobserved(GAPS, now=minutes(30), min_duration=dt.timedelta(minutes=1))
    assert (gap.start, gap.end) == (minutes(40), minutes(100))


def test_no_gap_long_enough_means_none():
    assert next_unobserved(GAPS, now=minutes(0), min_duration=dt.timedelta(hours=2)) is None
    assert next_unobserved([], now=minutes(0), min_duration=dt.timedelta(minutes=1)) is None


def test_gaps_need_not_arrive_in_order():
    gap = next_unobserved(list(reversed(GAPS)), now=minutes(0), min_duration=dt.timedelta(minutes=5))
    assert (gap.start, gap.end) == (minutes(0), minutes(10))


def test_a_negative_reaction_time_or_a_naive_now_is_refused():
    with pytest.raises(ValueError, match="min_duration"):
        next_unobserved(GAPS, now=minutes(0), min_duration=dt.timedelta(minutes=-1))
    with pytest.raises(ValueError, match="timezone"):
        next_unobserved(GAPS, now=minutes(0).replace(tzinfo=None), min_duration=dt.timedelta(minutes=1))
