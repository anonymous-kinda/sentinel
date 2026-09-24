"""End to end over the exercise day: catalog, snapshot, provider, gaps."""

import datetime as dt

import pytest

from sentinel.passes.gaps import GAP_LABEL, next_unobserved, unobserved_gaps
from sentinel.passes.providers.skyfield_local import SkyfieldProvider

from .exercise import END, EXERCISE_UNIT, START


@pytest.fixture(scope="module")
def day(catalog_match):
    windows = SkyfieldProvider(catalog_match.element_sets).windows(EXERCISE_UNIT, catalog_match.imagers, START, END)
    return windows, unobserved_gaps(windows, START, END)


def test_the_day_splits_into_observed_time_and_labelled_gaps(day):
    windows, gaps = day
    assert any(w.usable for w in windows) and gaps, "a non-trivial day"
    assert all(g.label == GAP_LABEL for g in gaps)
    assert all(START <= g.start < g.end <= END for g in gaps)
    assert [g.start for g in gaps] == sorted(g.start for g in gaps)


def test_no_gap_overlaps_a_padded_usable_window(day):
    windows, gaps = day
    for g in gaps:
        for w in windows:
            if w.usable:
                a, b = w.padded
                assert not (a < g.end and g.start < b), (g, w.name)


def test_the_next_gap_is_at_least_the_units_reaction_time(day):
    _, gaps = day
    reaction = dt.timedelta(minutes=EXERCISE_UNIT.reaction_time_min)
    gap = next_unobserved(gaps, now=START, min_duration=reaction)
    assert gap is not None
    assert gap.end - gap.start >= reaction
    assert gap.start >= START
