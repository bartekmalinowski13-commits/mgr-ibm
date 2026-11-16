"""Inter-rater agreement between two independent verifiers of a reference BOM (TH-03).

Both verifiers build a BOM for the same design without seeing each other's work. Lines are
compared per **designator** (grouping into lines is a presentation choice), field by field:
value, footprint and MPN. Reported per field: raw agreement and Cohen's kappa (nominal
labels, normalised case-insensitively), plus every disagreement so the two verifiers can
reconcile them against the datasheet. A designator present in only one BOM is a coverage
disagreement and is listed separately.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from bomagent_bom.model import BomItem

FIELDS = ("value", "footprint", "mpn")


@dataclass(frozen=True)
class FieldAgreement:
    compared: int
    agreed: int
    kappa: float

    @property
    def agreement(self) -> float:
        return self.agreed / self.compared if self.compared else math.nan


@dataclass(frozen=True)
class Disagreement:
    refdes: str
    field: str
    a: str
    b: str


@dataclass(frozen=True)
class AgreementReport:
    designators_compared: int
    only_in_one: list[str]
    fields: dict[str, FieldAgreement]
    disagreements: list[Disagreement] = field(default_factory=list)


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    """Cohen's kappa for two raters over nominal labels; NaN for no items.

    With a single observed category and full agreement kappa is defined as 1."""
    if len(a) != len(b):
        raise ValueError("ratings must have the same length")
    n = len(a)
    if n == 0:
        return math.nan
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in ca.keys() | cb.keys()) / (n * n)
    if expected >= 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def _label(item: BomItem, name: str) -> str:
    raw = {"value": item.value, "footprint": item.footprint, "mpn": item.mpn}[name]
    return " ".join(raw.casefold().split())


def _by_designator(items: Sequence[BomItem]) -> dict[str, BomItem]:
    return {r: item for item in items if not item.dnp for r in item.refdes}


def compare_verifiers(a: Sequence[BomItem], b: Sequence[BomItem]) -> AgreementReport:
    """Agreement of two verifiers' BOMs (DNP lines are ignored, as in scoring)."""
    left, right = _by_designator(a), _by_designator(b)
    common = sorted(left.keys() & right.keys())
    labels_a: dict[str, list[str]] = {f: [] for f in FIELDS}
    labels_b: dict[str, list[str]] = {f: [] for f in FIELDS}
    disagreements: list[Disagreement] = []
    for refdes in common:
        for name in FIELDS:
            x, y = _label(left[refdes], name), _label(right[refdes], name)
            labels_a[name].append(x)
            labels_b[name].append(y)
            if x != y:
                disagreements.append(Disagreement(refdes, name, x, y))
    fields = {
        name: FieldAgreement(
            compared=len(common),
            agreed=sum(x == y for x, y in zip(labels_a[name], labels_b[name], strict=True)),
            kappa=cohens_kappa(labels_a[name], labels_b[name]),
        )
        for name in FIELDS
    }
    return AgreementReport(
        designators_compared=len(common),
        only_in_one=sorted(left.keys() ^ right.keys()),
        fields=fields,
        disagreements=disagreements,
    )


def agreement_markdown(report: AgreementReport) -> str:
    """Table for the thesis (chapter 6) and the dataset's SOURCE.md."""
    lines = [
        f"Designators compared: {report.designators_compared}; "
        f"only in one BOM: {', '.join(report.only_in_one) or 'none'}",
        "",
        "| field | agreement | Cohen's kappa |",
        "|---|---|---|",
    ]
    for name, f in report.fields.items():
        lines.append(f"| {name} | {f.agreement:.3f} | {f.kappa:.3f} |")
    return "\n".join(lines) + "\n"
