"""Error injection for validation effectiveness (thesis metric "skuteczność walidacji").

Variant-neutral scoring (review of M1): an injected error counts as detected when a
*new* finding - one not already raised on the clean BOM - points at the affected
designator or line **and** either names the affected field or uses one of the rule
codes listed for that error kind. A variant's LLM validator therefore gets credit for
``field="footprint"`` on the right part even if it uses its own finding codes. Findings
on the mutated BOM that match no injected error are false alarms.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from bomagent_bom.model import BomItem, Finding, Severity
from bomagent_bom.packages import package_from_part_number

# kind -> (field the error is in, rule codes that also count as detection)
ERROR_KINDS: dict[str, tuple[str, frozenset[str]]] = {
    "footprint_size_swap": ("footprint", frozenset({"footprint.package_match"})),
    "quantity_off_by_one": ("quantity", frozenset({"quantity.matches_refdes", "schema.valid"})),
    "duplicate_refdes": ("refdes", frozenset({"refdes.unique"})),
    "invalid_value": ("value", frozenset({"value.parsable", "value.range"})),
    "drop_footprint": ("footprint", frozenset({"footprint.present"})),
    "drop_mpn": ("mpn", frozenset({"mpn.present"})),
}
DETECTED_BY = {k: codes for k, (_, codes) in ERROR_KINDS.items()}
_SIZE_SWAP = {"0402": "0603", "0603": "0805", "0805": "0603", "1206": "0805", "0201": "0402"}
_ACTIONABLE = {Severity.ERROR, Severity.WARNING}


@dataclass(frozen=True)
class InjectedError:
    kind: str
    line: int
    refdes: str
    detail: str

    @property
    def field(self) -> str:
        return ERROR_KINDS[self.kind][0]


@dataclass(frozen=True)
class DetectionReport:
    injected: int
    detected: int
    new_findings: int
    false_alarms: int

    @property
    def detection_rate(self) -> float:
        return self.detected / self.injected

    @property
    def false_alarm_rate(self) -> float:
        return self.false_alarms / self.new_findings if self.new_findings else 0.0


def _swap_size(item: BomItem) -> BomItem | None:
    """Only for parts whose MPN encodes the size - otherwise the error is undetectable by
    construction and would measure the injector, not the validator."""
    if not item.package or item.package not in _SIZE_SWAP:
        return None
    if package_from_part_number(item.mpn) != item.package:
        return None
    new = _SIZE_SWAP[item.package]
    fp = item.footprint.replace(item.package, new)
    return item.model_copy(update={"footprint": fp, "package": new})


def inject_errors(
    items: list[BomItem], *, n: int = 5, seed: int = 0, kinds: tuple[str, ...] | None = None
) -> tuple[list[BomItem], list[InjectedError]]:
    """Return a mutated copy of ``items`` with up to ``n`` errors (each on a distinct line)."""
    rng = random.Random(seed)  # noqa: S311 - reproducibility, not security
    kinds = kinds or tuple(ERROR_KINDS)
    out = [i.model_copy(deep=True) for i in items]
    errors: list[InjectedError] = []
    lines = list(range(len(out)))
    rng.shuffle(lines)
    for idx in lines:
        if len(errors) >= n:
            break
        item = out[idx]
        if item.dnp:
            continue
        kind = rng.choice(kinds)
        mutated: BomItem | None = None
        detail = ""
        if kind == "footprint_size_swap" and item.mpn:
            mutated = _swap_size(item)
            detail = "footprint size changed, MPN kept"
        elif kind == "quantity_off_by_one":
            mutated = item.model_copy(update={"quantity": item.quantity + 1})
            detail = f"quantity {item.quantity} -> {item.quantity + 1}"
        elif kind == "duplicate_refdes" and len(out) > 1:
            dup = out[(idx + 1) % len(out)].refdes[0]
            if dup not in item.refdes:
                mutated = item.model_copy(
                    update={"refdes": [*item.refdes, dup], "quantity": item.quantity + 1}
                )
                detail = f"{dup} also listed on line {item.line}"
        elif kind == "invalid_value" and item.kind in {"resistor", "capacitor", "inductor"}:
            mutated = item.model_copy(update={"value": "n/a"})
            detail = "value replaced by n/a"
        elif kind == "drop_footprint" and item.footprint and item.kind != "test_point":
            mutated = item.model_copy(update={"footprint": "", "package": None})
            detail = "footprint removed"
        elif kind == "drop_mpn" and item.mpn and item.kind not in {"test_point", "mechanical"}:
            mutated = item.model_copy(update={"mpn": "", "manufacturer": ""})
            detail = "MPN removed"
        if mutated is None:
            continue
        out[idx] = mutated
        ref = mutated.refdes[-1] if kind == "duplicate_refdes" else mutated.refdes[0]
        errors.append(InjectedError(kind, mutated.line, ref, detail))
    return out, errors


def _key(f: Finding) -> tuple[str, tuple[str, ...], str | None]:
    return (f.rule_id, tuple(f.refdes), f.field)


def _matches(error: InjectedError, f: Finding) -> bool:
    if error.refdes not in f.refdes and f.line != error.line:
        return False
    return f.rule_id in ERROR_KINDS[error.kind][1] or f.field == error.field


def detection_report(
    errors: list[InjectedError],
    findings: list[Finding],
    baseline: list[Finding] | None = None,
) -> DetectionReport:
    if not errors:
        raise ValueError("detection needs at least one injected error")
    known = {_key(f) for f in baseline or []}
    new = [f for f in findings if f.severity in _ACTIONABLE and _key(f) not in known]
    detected = sum(1 for e in errors if any(_matches(e, f) for f in new))
    false_alarms = sum(1 for f in new if not any(_matches(e, f) for e in errors))
    return DetectionReport(len(errors), detected, len(new), false_alarms)


def detection_rate(
    errors: list[InjectedError], findings: list[Finding], baseline: list[Finding] | None = None
) -> float:
    return detection_report(errors, findings, baseline).detection_rate
