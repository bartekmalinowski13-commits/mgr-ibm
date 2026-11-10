"""Statistics for the thesis experiment (chapter 6): paired comparisons of variants."""

from __future__ import annotations

import math

import pytest

from bomagent_eval.experiment_stats import bootstrap_ci, compare_paired


def test_bootstrap_ci_is_deterministic_and_contains_the_mean():
    values = [0.8, 0.9, 0.85, 0.95, 0.7, 0.88]
    lo, hi = bootstrap_ci(values, seed=7)
    assert (lo, hi) == bootstrap_ci(values, seed=7)
    assert lo <= sum(values) / len(values) <= hi
    assert bootstrap_ci([0.5], seed=1) == (0.5, 0.5)
    assert all(math.isnan(x) for x in bootstrap_ci([], seed=1))


def test_paired_comparison_detects_a_consistent_difference():
    a = [0.70, 0.72, 0.68, 0.75, 0.71, 0.69, 0.73, 0.70]
    b = [x + 0.15 for x in a]
    result = compare_paired(a, b, seed=3)
    assert result.n == 8
    assert result.mean_diff == pytest.approx(0.15)
    assert result.p_value < 0.01
    assert result.ci_low > 0
    assert result.wins_b == 8
    assert result.wins_a == 0


def test_no_difference_gives_p_one_and_skips_undefined_pairs():
    a = [0.5, 0.6, math.nan, 0.7]
    b = [0.5, 0.6, 0.9, 0.7]
    result = compare_paired(a, b, seed=1)
    assert result.n == 3  # the NaN pair is dropped
    assert result.mean_diff == 0
    assert result.p_value == 1.0
    with pytest.raises(ValueError, match="same length"):
        compare_paired([1.0], [1.0, 2.0])
