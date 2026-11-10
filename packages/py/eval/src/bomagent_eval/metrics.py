"""BOM quality metrics (thesis Tab. 6.1).

Definitions are written to be fair to both variants (review of M1):

* **Line P/R/F1** - predicted lines matched to reference lines by the largest designator
  overlap (Jaccard >= 0.5, greedy). The reference groups identical parts on one line
  regardless of how the schematic happened to annotate them.
* **Designator P/R/F1** - per reference designator; a designator listed on several
  predicted lines counts once as TP and every extra listing as FP.
* **Field accuracy** - two numbers per field: ``accuracy`` over designators present in
  both BOMs, and ``accuracy_ref`` over *all* reference designators (a missing part counts
  as wrong), so a BOM listing only one correct part cannot score 100 %.
* **MPN metrics** - ``coverage`` (reference parts that received any MPN),
  ``out_of_reference`` (predicted MPN is neither the reference MPN nor an accepted
  alternate) and ``unverified`` (predicted MPN found in no trusted catalogue: knowledge
  base snapshot, input design, reference). ``unverified`` - the hallucination rate - is
  only computed when a catalogue is supplied; otherwise it is NaN, never a guess.
* Undefined ratios (empty denominators) are NaN and are skipped by aggregation.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from bomagent_bom.model import BomItem, BomVersion, Usage
from bomagent_bom.values import values_equivalent

MATCH_THRESHOLD = 0.5
FIELDS = ("value", "footprint", "mpn", "manufacturer", "dnp", "quantity")
NAN = float("nan")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
MANUFACTURER_ALIASES = {
    "ti": "texasinstruments",
    "adi": "analogdevices",
    "maxim": "analogdevices",
    "maximintegrated": "analogdevices",
    "linear": "analogdevices",
    "lineartechnology": "analogdevices",
    "st": "stmicroelectronics",
    "stm": "stmicroelectronics",
    "nxp": "nxpsemiconductors",
    "onsemi": "onsemiconductor",
    "sem": "samsungelectromechanics",
    "samsung": "samsungelectromechanics",
    "murataelectronics": "murata",
    "muratamanufacturing": "murata",
    "yageocorporation": "yageo",
    "vishaydale": "vishay",
    "microchiptechnology": "microchip",
}


def norm_mpn(mpn: str) -> str:
    return re.sub(r"\s+", "", mpn).upper()


def norm_manufacturer(name: str) -> str:
    key = _NON_ALNUM.sub("", name.casefold())
    for suffix in ("incorporated", "inc", "corporation", "corp", "ltd", "gmbh", "co"):
        if key.endswith(suffix) and len(key) > len(suffix) + 2:
            key = key[: -len(suffix)]
            break
    return MANUFACTURER_ALIASES.get(key, key)


def norm_footprint(fp: str) -> str:
    return fp.split(":", 1)[-1].strip().casefold()


def _ratio(num: int, den: int) -> float:
    return num / den if den else NAN


class PRF(BaseModel):
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float:
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> float:
        if self.tp + self.fp + self.fn == 0:
            return NAN
        return 2 * self.tp / (2 * self.tp + self.fp + self.fn)


class FieldScore(BaseModel):
    correct: int = 0
    compared: int = 0
    reference_total: int = 0

    @property
    def accuracy(self) -> float:
        return _ratio(self.correct, self.compared)

    @property
    def accuracy_ref(self) -> float:
        return _ratio(self.correct, self.reference_total)


class MpnMetrics(BaseModel):
    predicted: int = 0
    reference_parts: int = 0
    covered: int = 0
    out_of_reference: int = 0
    unverified: int = 0
    catalogue_checked: bool = False
    examples: list[str] = Field(default_factory=list)

    @property
    def coverage(self) -> float:
        return _ratio(self.covered, self.reference_parts)

    @property
    def out_of_reference_rate(self) -> float:
        return _ratio(self.out_of_reference, self.predicted)

    @property
    def rate(self) -> float:
        """Hallucination rate: MPNs absent from every trusted catalogue (NaN if unchecked)."""
        return _ratio(self.unverified, self.predicted) if self.catalogue_checked else NAN


# backwards-compatible name used in reports
Hallucinations = MpnMetrics


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
    hallucinations: MpnMetrics
    usage: Usage = Field(default_factory=Usage)
    diffs: list[ItemDiff] = Field(default_factory=list)

    def summary(self) -> dict[str, float]:
        h = self.hallucinations
        out = {
            "line_precision": self.lines.precision,
            "line_recall": self.lines.recall,
            "line_f1": self.lines.f1,
            "designator_f1": self.designators.f1,
            "mpn_coverage": h.coverage,
            "mpn_out_of_reference_rate": h.out_of_reference_rate,
            "mpn_hallucination_rate": h.rate,
            "input_tokens": float(self.usage.input_tokens),
            "output_tokens": float(self.usage.output_tokens),
            "llm_calls": float(self.usage.llm_calls),
            "cost_eur": self.usage.cost_eur,
            "wall_time_s": self.usage.wall_time_s,
        }
        out |= {f"acc_{k}": v.accuracy for k, v in self.fields.items()}
        out |= {f"acc_ref_{k}": v.accuracy_ref for k, v in self.fields.items()}
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


def _accepted_mpns(ref: BomItem) -> set[str]:
    return {norm_mpn(ref.mpn)} | {
        norm_mpn(a) for a in ref.fields.get("mpn_alternates", "").split() if a
    }


def _mfr_ok(pred: str, ref: str) -> bool:
    a, b = norm_manufacturer(pred), norm_manufacturer(ref)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 5 and long_.startswith(short)


def evaluate(
    predicted: BomVersion | list[BomItem],
    reference: list[BomItem],
    *,
    known_mpns: set[str] | None = None,
    design_mpns: set[str] | None = None,
    design: str = "",
    variant: str = "",
    model: str = "",
    max_diffs: int = 200,
) -> EvalReport:
    pred_items = predicted.items if isinstance(predicted, BomVersion) else predicted
    usage = predicted.usage if isinstance(predicted, BomVersion) else Usage()
    m = match_lines(pred_items, reference)
    lines = PRF(tp=len(m.pairs), fp=len(m.unmatched_pred), fn=len(m.unmatched_ref))

    pred_by_ref: dict[str, BomItem] = {}
    duplicate_listings = 0
    for item in pred_items:
        for r in item.refdes:
            if r in pred_by_ref:
                duplicate_listings += 1  # first listing is the one scored
            else:
                pred_by_ref[r] = item
    ref_by_ref = {r: i for i in reference for r in i.refdes}
    common = set(pred_by_ref) & set(ref_by_ref)
    designators = PRF(
        tp=len(common),
        fp=len(set(pred_by_ref) - set(ref_by_ref)) + duplicate_listings,
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

    for r, e in ref_by_ref.items():
        scores["value"].reference_total += 1
        scores["footprint"].reference_total += 1
        scores["dnp"].reference_total += 1
        scores["mpn"].reference_total += bool(e.mpn)
        scores["manufacturer"].reference_total += bool(e.manufacturer)
        if r not in common and len(diffs) < max_diffs:
            diffs.append(ItemDiff(refdes=r, field="missing", predicted="", expected=e.value))
    scores["quantity"].reference_total = len(reference)

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
            score("mpn", norm_mpn(p.mpn) in _accepted_mpns(e), r, p.mpn, e.mpn)
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

    mpn = _mpn_metrics(pred_items, reference, pred_by_ref, ref_by_ref, known_mpns, design_mpns)

    return EvalReport(
        design=design,
        variant=variant,
        model=model,
        lines=lines,
        designators=designators,
        fields=scores,
        hallucinations=mpn,
        usage=usage,
        diffs=diffs,
    )


def _mpn_metrics(
    pred_items: list[BomItem],
    reference: list[BomItem],
    pred_by_ref: dict[str, BomItem],
    ref_by_ref: dict[str, BomItem],
    known_mpns: set[str] | None,
    design_mpns: set[str] | None,
) -> MpnMetrics:
    mpn = MpnMetrics(catalogue_checked=known_mpns is not None)
    reference_mpns: set[str] = set()
    for e in reference:
        reference_mpns |= _accepted_mpns(e) - {""}
    trusted = (
        {norm_mpn(x) for x in (known_mpns or set())}
        | {norm_mpn(x) for x in (design_mpns or set())}
        | reference_mpns
    )
    for r, e in ref_by_ref.items():
        if e.mpn and not e.dnp:
            mpn.reference_parts += 1
            if r in pred_by_ref and pred_by_ref[r].mpn:
                mpn.covered += 1
    for p in pred_items:
        if not p.mpn:
            continue
        mpn.predicted += 1
        n = norm_mpn(p.mpn)
        if n not in reference_mpns:
            mpn.out_of_reference += 1
        if n not in trusted:
            mpn.unverified += 1
            if len(mpn.examples) < 20:
                mpn.examples.append(p.mpn)
    return mpn


def isnan(x: float) -> bool:
    return isinstance(x, float) and math.isnan(x)
