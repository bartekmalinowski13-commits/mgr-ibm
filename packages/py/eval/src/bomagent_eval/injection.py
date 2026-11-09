"""Error injection for measuring validation effectiveness (thesis metric
"skuteczność walidacji na błędach wstrzykniętych").

Each injected error has an expected detecting check; ``detection_rate`` counts an error
as detected when any finding of a matching code mentions the affected designator (or, for
line-level errors, the affected line).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from bomagent_bom.model import BomItem, Finding
from bomagent_bom.packages import package_from_part_number

# kind -> finding codes that count as detection
DETECTED_BY: dict[str, frozenset[str]] = {
    "footprint_size_swap": frozenset({"footprint.package_match"}),
    "quantity_off_by_one": frozenset({"quantity.matches_refdes", "schema.valid"}),
    "duplicate_refdes": frozenset({"refdes.unique"}),
    "invalid_value": frozenset({"value.parsable", "value.range"}),
    "drop_footprint": frozenset({"footprint.present"}),
    "drop_mpn": frozenset({"mpn.present"}),
}
_SIZE_SWAP = {"0402": "0603", "0603": "0805", "0805": "0603", "1206": "0805", "0201": "0402"}


@dataclass(frozen=True)
class InjectedError:
    kind: str
    line: int
    refdes: str
    detail: str


def _swap_size(item: BomItem) -> BomItem | None:
    """Only for parts whose MPN encodes the size - otherwise the error is undetectable by
    construction and would measure the injector, not the validator."""
    if not item.package or item.package not in _SIZE_SWAP:
        return None
    if package_from_part_number(item.mpn) != item.package:
        return None
    new = _SIZE_SWAP[item.package]
    fp = item.footprint.replace(item.package, new)
    # footprint now disagrees with the MPN, which still encodes the old size
    return item.model_copy(update={"footprint": fp, "package": new})


def inject_errors(
    items: list[BomItem], *, n: int = 5, seed: int = 0, kinds: tuple[str, ...] | None = None
) -> tuple[list[BomItem], list[InjectedError]]:
    """Return a mutated copy of ``items`` with up to ``n`` errors (each on a distinct line)."""
    rng = random.Random(seed)  # noqa: S311 - reproducibility, not security
    kinds = kinds or tuple(DETECTED_BY)
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
        elif kind == "duplicate_refdes" and idx > 0:
            other = out[(idx + 1) % len(out)]
            dup = other.refdes[0]
            if dup not in item.refdes:
                mutated = item.model_copy(
                    update={"refdes": [*item.refdes, dup], "quantity": item.quantity + 1}
                )
                detail = f"{dup} also listed on line {item.line}"
        elif kind == "invalid_value" and item.kind in {"resistor", "capacitor", "inductor"}:
            mutated = item.model_copy(update={"value": "n/a"})
            detail = "value replaced by n/a"
        elif kind == "drop_footprint" and item.kind != "test_point":
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


def detection_rate(errors: list[InjectedError], findings: list[Finding]) -> float:
    if not errors:
        return 1.0
    detected = 0
    for e in errors:
        codes = DETECTED_BY[e.kind]
        if any(f.rule_id in codes and (e.refdes in f.refdes or f.line == e.line) for f in findings):
            detected += 1
    return detected / len(errors)
