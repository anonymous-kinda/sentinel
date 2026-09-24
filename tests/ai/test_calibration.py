"""Calibration metrics, checked against values computed by hand.

pairs = (stated confidence, was the choice right)
"""

import pytest

from sentinel.ai.calibration import brier, ece, reliability

PAIRS = [(0.9, True), (0.9, False), (0.6, True), (0.2, False)]


def test_brier_is_the_mean_squared_gap_between_confidence_and_outcome():
    # (0.1² + 0.9² + 0.4² + 0.2²) / 4 = 1.02 / 4
    assert brier(PAIRS) == pytest.approx(0.255)


def test_reliability_bins_confidence_and_report_observed_accuracy():
    bins = {round(b.lo, 1): b for b in reliability(PAIRS, bins=10) if b.count}
    assert sorted(bins) == [0.2, 0.6, 0.9]
    top = bins[0.9]
    assert (top.count, top.confidence, top.accuracy) == (2, pytest.approx(0.9), 0.5)
    assert len(reliability(PAIRS, bins=10)) == 10


def test_ece_weights_each_bins_gap_by_its_share_of_cases():
    # 2/4·|0.5-0.9| + 1/4·|1-0.6| + 1/4·|0-0.2| = 0.2 + 0.1 + 0.05
    assert ece(PAIRS, bins=10) == pytest.approx(0.35)


def test_a_confidence_of_one_lands_in_the_top_bin():
    [top] = [b for b in reliability([(1.0, True)], bins=10) if b.count]
    assert top.lo == pytest.approx(0.9) and top.hi == pytest.approx(1.0)


def test_no_choices_means_no_score_rather_than_zero():
    assert brier([]) is None and ece([]) is None
