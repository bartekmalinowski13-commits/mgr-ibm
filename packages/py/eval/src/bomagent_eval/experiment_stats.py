"""Statistics of the variant comparison (thesis chapter 6.4), without heavy dependencies.

Runs are paired: the same design, model and repetition index is run with variant A and
variant B. Differences are tested with an exact-or-Monte-Carlo **paired permutation
(sign-flip) test** on the mean difference, and summarised with a percentile **bootstrap
confidence interval**. Both are distribution-free, which suits small evaluation sets
and bounded metrics such as F1. Seeds make every number in the report reproducible.
"""

from __future__ import annotations

import itertools
import math
import random
import statistics
from collections.abc import Callable, Sequence

from pydantic import BaseModel

EXACT_LIMIT = 16  # up to 2**16 sign patterns are enumerated exactly


def bootstrap_ci(
    values: Sequence[float],
    *,
    stat: Callable[[Sequence[float]], float] = statistics.fmean,
    level: float = 0.95,
    resamples: int = 4000,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap interval of ``stat``; NaN values are ignored."""
    data = [v for v in values if not math.isnan(v)]
    if not data:
        return (math.nan, math.nan)
    if len(data) == 1:
        return (data[0], data[0])
    rng = random.Random(seed)  # noqa: S311 - statistical resampling, seeded for reproducibility
    stats = sorted(stat(rng.choices(data, k=len(data))) for _ in range(resamples))
    alpha = (1 - level) / 2
    return (stats[int(alpha * (resamples - 1))], stats[int((1 - alpha) * (resamples - 1))])


class PairedComparison(BaseModel):
    n: int
    mean_a: float
    mean_b: float
    mean_diff: float  # B - A
    ci_low: float
    ci_high: float
    p_value: float
    wins_a: int
    wins_b: int
    ties: int


def _p_value(diffs: list[float], *, resamples: int, rng: random.Random) -> float:
    observed = abs(statistics.fmean(diffs))
    if observed == 0:
        return 1.0
    eps = 1e-12
    if len(diffs) <= EXACT_LIMIT:
        hits = total = 0
        for signs in itertools.product((1, -1), repeat=len(diffs)):
            total += 1
            if (
                abs(statistics.fmean(s * d for s, d in zip(signs, diffs, strict=True)))
                >= observed - eps
            ):
                hits += 1
        return hits / total
    hits = sum(
        1
        for _ in range(resamples)
        if abs(statistics.fmean(d if rng.random() < 0.5 else -d for d in diffs)) >= observed - eps
    )
    return (hits + 1) / (resamples + 1)


def compare_paired(
    a: Sequence[float],
    b: Sequence[float],
    *,
    resamples: int = 10000,
    seed: int = 0,
) -> PairedComparison:
    """Compare paired measurements of variant A and B (pairs with NaN are dropped)."""
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    pairs = [(x, y) for x, y in zip(a, b, strict=True) if not (math.isnan(x) or math.isnan(y))]
    if not pairs:
        nan = math.nan
        return PairedComparison(
            n=0,
            mean_a=nan,
            mean_b=nan,
            mean_diff=nan,
            ci_low=nan,
            ci_high=nan,
            p_value=nan,
            wins_a=0,
            wins_b=0,
            ties=0,
        )
    diffs = [y - x for x, y in pairs]
    rng = random.Random(seed)  # noqa: S311 - statistical resampling, seeded for reproducibility
    lo, hi = bootstrap_ci(diffs, resamples=resamples // 2 or 1, seed=seed)
    return PairedComparison(
        n=len(pairs),
        mean_a=statistics.fmean(x for x, _ in pairs),
        mean_b=statistics.fmean(y for _, y in pairs),
        mean_diff=statistics.fmean(diffs),
        ci_low=lo,
        ci_high=hi,
        p_value=_p_value(diffs, resamples=resamples, rng=rng),
        wins_a=sum(1 for d in diffs if d < 0),
        wins_b=sum(1 for d in diffs if d > 0),
        ties=sum(1 for d in diffs if d == 0),
    )
