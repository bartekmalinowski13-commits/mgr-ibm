"""Aggregation over repeated runs (thesis PB3: repeatability) and run comparison."""

from __future__ import annotations

import itertools
import math
import statistics
from collections.abc import Sequence

from pydantic import BaseModel

from bomagent_bom.model import BomVersion
from bomagent_bom.values import normalize_value
from bomagent_eval.metrics import EvalReport, norm_mpn


class Aggregate(BaseModel):
    n: int
    mean: dict[str, float]
    stdev: dict[str, float]
    count: dict[str, int]


def aggregate(reports: Sequence[EvalReport]) -> Aggregate:
    """Mean/stdev per metric over runs; undefined (NaN) values are skipped and the number
    of defined values is reported in ``count``."""
    if not reports:
        return Aggregate(n=0, mean={}, stdev={}, count={})
    keys = reports[0].summary().keys()
    values = {k: [v for r in reports if not math.isnan(v := r.summary()[k])] for k in keys}
    return Aggregate(
        n=len(reports),
        mean={k: statistics.fmean(v) if v else math.nan for k, v in values.items()},
        stdev={k: statistics.stdev(v) if len(v) > 1 else 0.0 for k, v in values.items()},
        count={k: len(v) for k, v in values.items()},
    )


def assignment(bom: BomVersion) -> dict[str, tuple[str, str]]:
    """designator -> (value, MPN) decided by a run. Values are re-normalised here, so
    two runs writing ``4k7`` and ``4.7 kΩ`` agree (formatting is not disagreement)."""
    return {
        r: ((normalize_value(i.value, i.kind) or i.value).casefold(), norm_mpn(i.mpn))
        for i in bom.items
        for r in i.refdes
    }


def pairwise_agreement(boms: Sequence[BomVersion]) -> float:
    """Mean share of designators with identical decisions across all pairs of runs."""
    if len(boms) < 2:
        return 1.0
    scores: list[float] = []
    for a, b in itertools.combinations([assignment(x) for x in boms], 2):
        keys = set(a) | set(b)
        same = sum(1 for k in keys if a.get(k) == b.get(k))
        scores.append(same / len(keys) if keys else 1.0)
    return statistics.fmean(scores)
