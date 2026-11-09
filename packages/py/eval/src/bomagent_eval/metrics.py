"""BOM quality metrics (thesis Tab. 6.1).

* **Line P/R/F1** - predicted lines are matched to reference lines by the largest
  designator overlap (Jaccard >= 0.5, greedy); unmatched predicted lines are false
  positives, unmatched reference lines false negatives.
* **Designator P/R/F1** - per reference designator (catches invented or missing parts).
* **Field accuracy** - for each designator present in both BOMs: value (unit-aware),
  footprint, MPN (reference MPN or an accepted alternate), manufacturer, DNP; quantity is
  compared on matched lines.
* **MPN hallucination rate** - share of predicted MPNs that exist in *no* trusted source
  (reference, alternates, input design, knowledge-base catalogue passed as ``known_mpns``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from bomagent_bom.model import BomItem, BomVersion, Usage
from bomagent_bom.values import values_equivalent

MATCH_THRESHOLD = 0.5
FIELDS = ("value", "footprint", "mpn", "manufacturer", "dnp", "quantity")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def norm_mpn(mpn: str) -> str:
    return re.sub(r"\s+", "", mpn).upper()


def norm_manufacturer(name: str) -> str:
    return _NON_ALNUM.sub("", name.casefold())


def norm_footprint(fp: str) -> str:
    return fp.split(":", 1)[-1].strip().casefold()


class PRF(BaseModel):
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
        }


class FieldScore(BaseModel):
    correct: int = 0
    compared: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.compared if self.compared else 0.0


class Hallucinations(BaseModel):
    predicted_mpns: int = 0
    hallucinated: int = 0
    examples: list[str] = Field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.hallucinated / self.predicted_mpns if self.predicted_mpns else 0.0


class ItemDiff(BaseModel):
    refdes: str
    field: str
    predicted: str
    expected: str


class EvalReport(BaseModel):
    design: str
    variant: str = ""
    model: str = ""
    lines: PRF
    designators: PRF
    fields: dict[str, FieldScore]
    hallucinations: Hallucinations
    usage: Usage = Field(default_factory=Usage)
    diffs: list[ItemDiff] = Field(default_factory=list)

    def summary(self) -> dict[str, float]:
        out = {
            "line_precision": self.lines.precision,
            "line_recall": self.lines.recall,
            "line_f1": self.lines.f1,
            "designator_f1": self.designators.f1,
            "mpn_hallucination_rate": self.hallucinations.rate,
            "input_tokens": float(self.usage.input_tokens),
            "output_tokens": float(self.usage.output_tokens),
            "llm_calls": float(self.usage.llm_calls),
            "cost_eur": self.usage.cost_eur,
            "wall_time_s": self.usage.wall_time_s,
        }
        out |= {f"acc_{k}": v.accuracy for k, v in self.fields.items()}
        return out


@dataclass
class _Match:
    pairs: list[tuple[BomItem, BomItem]] = field(default_factory=list)
    unmatched_pred: list[BomItem] = field(default_factory=list)
    unmatched_ref: list[BomItem] = field(default_factory=list)


def match_lines(pred: list[BomItem], ref: list[BomItem]) -> _Match:
    candidates: list[tuple[float, int, int]] = []
    for i, p in enumerate(pred):
        ps = set(p.refdes)
        for j, r in enumerate(ref):
            rs = set(r.refdes)
            inter = len(ps & rs)
            if inter:
                candidates.append((inter / len(ps | rs), i, j))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    used_p: set[int] = set()
    used_r: set[int] = set()
    m = _Match()
    for score, i, j in candidates:
        if score < MATCH_THRESHOLD or i in used_p or j in used_r:
            continue
        used_p.add(i)
        used_r.add(j)
        m.pairs.append((pred[i], ref[j]))
    m.unmatched_pred = [p for i, p in enumerate(pred) if i not in used_p]
    m.unmatched_ref = [r for j, r in enumerate(ref) if j not in used_r]
    return m


def _mpn_ok(pred: BomItem, ref: BomItem) -> bool:
    accepted = {norm_mpn(ref.mpn)} | {
        norm_mpn(a) for a in ref.fields.get("mpn_alternates", "").split() if a
    }
    return norm_mpn(pred.mpn) in accepted


def _mfr_ok(pred: str, ref: str) -> bool:
    a, b = norm_manufacturer(pred), norm_manufacturer(ref)
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


def evaluate(
    predicted: BomVersion | list[BomItem],
    reference: list[BomItem],
    *,
    known_mpns: set[str] | None = None,
    design: str = "",
    variant: str = "",
    model: str = "",
    max_diffs: int = 200,
) -> EvalReport:
    pred_items = predicted.items if isinstance(predicted, BomVersion) else predicted
    usage = predicted.usage if isinstance(predicted, BomVersion) else Usage()
    m = match_lines(pred_items, reference)
    lines = PRF(tp=len(m.pairs), fp=len(m.unmatched_pred), fn=len(m.unmatched_ref))

    pred_by_ref = {r: i for i in pred_items for r in i.refdes}
    ref_by_ref = {r: i for i in reference for r in i.refdes}
    common = set(pred_by_ref) & set(ref_by_ref)
    designators = PRF(
        tp=len(common),
        fp=len(set(pred_by_ref) - set(ref_by_ref)),
        fn=len(set(ref_by_ref) - set(pred_by_ref)),
    )

    scores = {f: FieldScore() for f in FIELDS}
    diffs: list[ItemDiff] = []

    def score(name: str, ok: bool, refdes: str, got: str, want: str) -> None:
        scores[name].compared += 1
        if ok:
            scores[name].correct += 1
        elif len(diffs) < max_diffs:
            diffs.append(ItemDiff(refdes=refdes, field=name, predicted=got, expected=want))

    for r in sorted(common):
        p, e = pred_by_ref[r], ref_by_ref[r]
        score("value", values_equivalent(p.value, e.value, e.kind), r, p.value, e.value)
        score(
            "footprint",
            norm_footprint(p.footprint) == norm_footprint(e.footprint),
            r,
            p.footprint,
            e.footprint,
        )
        if e.mpn:
            score("mpn", _mpn_ok(p, e), r, p.mpn, e.mpn)
        if e.manufacturer:
            score(
                "manufacturer",
                _mfr_ok(p.manufacturer, e.manufacturer),
                r,
                p.manufacturer,
                e.manufacturer,
            )
        score("dnp", p.dnp == e.dnp, r, str(p.dnp), str(e.dnp))
    for p, e in m.pairs:
        score("quantity", p.quantity == e.quantity, e.refdes[0], str(p.quantity), str(e.quantity))

    trusted = {norm_mpn(x) for x in (known_mpns or set())}
    for e in reference:
        trusted.add(norm_mpn(e.mpn))
        trusted |= {norm_mpn(a) for a in e.fields.get("mpn_alternates", "").split()}
    hall = Hallucinations()
    for p in pred_items:
        if not p.mpn:
            continue
        hall.predicted_mpns += 1
        if norm_mpn(p.mpn) not in trusted:
            hall.hallucinated += 1
            if len(hall.examples) < 20:
                hall.examples.append(p.mpn)

    return EvalReport(
        design=design,
        variant=variant,
        model=model,
        lines=lines,
        designators=designators,
        fields=scores,
        hallucinations=hall,
        usage=usage,
        diffs=diffs,
    )
