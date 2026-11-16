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


def test_holm_adjustment_is_monotone_and_capped():
    from bomagent_eval.experiment_stats import holm_adjust

    adjusted = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03})
    # sorted p: 0.01*3, max(0.03*2, prev), max(0.04*1, prev)
    assert adjusted == pytest.approx({"a": 0.03, "b": 0.06, "c": 0.06})
    assert holm_adjust({"x": 0.6, "y": 0.9}) == pytest.approx({"x": 1.0, "y": 1.0})
    assert holm_adjust({}) == {}
    nan_case = holm_adjust({"a": 0.01, "b": math.nan})
    assert nan_case["a"] == pytest.approx(0.01)  # NaN is not counted in the family
    assert math.isnan(nan_case["b"])


def test_effect_size_is_standardised_paired_difference():
    a = [0.70, 0.72, 0.68, 0.75, 0.71, 0.69]
    b = [x + d for x, d in zip(a, [0.10, 0.12, 0.08, 0.11, 0.09, 0.10], strict=True)]
    result = compare_paired(a, b, seed=1)
    assert result.effect_size > 5  # a large consistent shift
    same = compare_paired([0.5, 0.5, 0.5], [0.6, 0.6, 0.6], seed=1)
    assert math.isnan(same.effect_size)  # zero spread of the differences: d_z undefined
    assert math.isnan(compare_paired([0.5], [0.7], seed=1).effect_size)  # n < 2


def test_cluster_bootstrap_resamples_designs_then_runs():
    from bomagent_eval.experiment_stats import cluster_bootstrap_ci

    clusters = [[0.1, 0.12, 0.11], [0.2, 0.18, 0.22], [0.15, 0.16, 0.14], [0.3, 0.28, 0.31]]
    lo, hi = cluster_bootstrap_ci(clusters, seed=5)
    assert (lo, hi) == cluster_bootstrap_ci(clusters, seed=5)
    grand = sum(sum(c) / len(c) for c in clusters) / len(clusters)
    assert lo <= grand <= hi
    # more spread between designs -> wider than within-design noise alone
    narrow = cluster_bootstrap_ci([[0.2, 0.2, 0.2]] * 4, seed=5)
    assert narrow == (pytest.approx(0.2), pytest.approx(0.2))
    assert all(math.isnan(x) for x in cluster_bootstrap_ci([], seed=1))
    assert cluster_bootstrap_ci([[0.4, math.nan]], seed=1) == (0.4, 0.4)
