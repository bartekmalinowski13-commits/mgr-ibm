"""Rule pack ``core`` v1.0.0 - deterministic BOM checks used by variant B.

Severity semantics: ``error`` = the BOM is wrong; ``warning`` = probably incomplete;
``review`` = a checklist item a qualified engineer must confirm (IEC 60601-1 items are
*flags*, not compliance verdicts - the tool supports, not replaces, the risk file);
``info`` = noteworthy.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from decimal import Decimal

import jsonschema

from bomagent_bom.model import (
    AppliedPart,
    BomItem,
    Finding,
    PowerSource,
    Requirements,
    Severity,
)
from bomagent_bom.packages import package_from_part_number, package_from_text
from bomagent_bom.schema import bom_item_json_schema
from bomagent_bom.values import ValueParseError, parse_value
from bomagent_rules.base import Rule, RuleContext, RulePack, finding

PACK_ID = "core"
PACK_VERSION = "1.0.0"
PASSIVE = {"resistor", "capacitor", "inductor"}
# kinds whose MPN / value text conventionally encode the chip size (0402, 0603, ...).
# For ICs, numbers like LT1206 or TPS2010 are part names, not sizes.
SIZE_CODED = PASSIVE | {"ferrite_bead", "led"}
EXPECTED_UNIT = {"resistor": "Ω", "capacitor": "F", "inductor": "H"}
# plausible physical ranges of discrete passives (base units)
RANGES: dict[str, tuple[Decimal, Decimal]] = {
    "resistor": (Decimal("0"), Decimal("1E9")),
    "capacitor": (Decimal("1E-13"), Decimal("10")),
    "inductor": (Decimal("1E-10"), Decimal("10")),
}
_ITEM_SCHEMA = bom_item_json_schema()
_VALIDATOR = jsonschema.Draft202012Validator(_ITEM_SCHEMA)
_ISOLATION_HINT = re.compile(
    r"\b(opto|isolat|iso\d|isow|adum|si8[4-7]|pc817|acpl-|hcpl-|tlp\d|6n13[5-9]|transformer"
    r"|dc[-/]?dc)",
    re.I,
)
_Y_CAP = re.compile(r"\b(Y1|Y2|X1Y2|safety)\b", re.I)


def _schema_valid(items: list[BomItem], _: RuleContext) -> Iterable[Finding]:
    for item in items:
        for err in _VALIDATOR.iter_errors(item.model_dump(mode="json")):
            path = ".".join(str(p) for p in err.absolute_path) or "item"
            yield finding("schema.valid", Severity.ERROR, f"{path}: {err.message}", item, path)


def _refdes_unique(items: list[BomItem], _: RuleContext) -> Iterable[Finding]:
    counts = Counter(r for item in items for r in item.refdes)
    for item in items:
        dup = [r for r in item.refdes if counts[r] > 1]
        if dup:
            yield finding(
                "refdes.unique",
                Severity.ERROR,
                f"designator(s) {', '.join(dup)} appear on more than one line",
                item,
                "refdes",
                dup,
            )


def _quantity_matches(items: list[BomItem], _: RuleContext) -> Iterable[Finding]:
    for item in items:
        if item.quantity != len(item.refdes):
            yield finding(
                "quantity.matches_refdes",
                Severity.ERROR,
                f"quantity {item.quantity} but {len(item.refdes)} designators",
                item,
                "quantity",
            )


def _footprint_present(items: list[BomItem], _: RuleContext) -> Iterable[Finding]:
    for item in items:
        if not item.dnp and not item.footprint and item.kind not in {"test_point"}:
            yield finding(
                "footprint.present", Severity.ERROR, "no footprint assigned", item, "footprint"
            )


def _mpn_present(items: list[BomItem], _: RuleContext) -> Iterable[Finding]:
    for item in items:
        if item.dnp or item.kind in {"test_point", "mechanical"}:
            continue
        if not item.mpn:
            yield finding(
                "mpn.present",
                Severity.WARNING,
                "no manufacturer part number - the part cannot be purchased as is",
                item,
                "mpn",
            )
        elif not item.manufacturer:
            yield finding(
                "manufacturer.present",
                Severity.WARNING,
                "MPN without manufacturer",
                item,
                "manufacturer",
            )


def _value_parsable(items: list[BomItem], _: RuleContext) -> Iterable[Finding]:
    for item in items:
        if item.kind not in PASSIVE:
            continue
        try:
            q = parse_value(item.value, item.kind).quantity
        except ValueParseError:
            yield finding(
                "value.parsable",
                Severity.ERROR,
                f"value {item.value!r} is not a valid {item.kind} value",
                item,
                "value",
            )
            continue
        if q.unit != EXPECTED_UNIT[item.kind]:
            yield finding(
                "value.unit_kind",
                Severity.ERROR,
                f"{q} is not a {item.kind} value (expected {EXPECTED_UNIT[item.kind]})",
                item,
                "value",
            )
            continue
        low, high = RANGES[item.kind]
        if not (low <= q.value <= high):
            yield finding(
                "value.range",
                Severity.ERROR,
                f"{q} is outside the plausible range for a {item.kind}",
                item,
                "value",
            )
        if item.kind == "resistor" and q.value == 0:
            yield finding("value.zero_ohm", Severity.INFO, "0 Ω jumper", item, "value")


def _package_consistent(items: list[BomItem], _: RuleContext) -> Iterable[Finding]:
    for item in items:
        if not item.package or item.kind not in SIZE_CODED:
            continue
        hints = {
            "mpn": package_from_part_number(item.mpn),
            "value": package_from_text(item.value),
            "description": package_from_text(item.description),
        }
        for source, pkg in hints.items():
            if pkg and pkg != item.package:
                yield finding(
                    "footprint.package_match",
                    Severity.ERROR,
                    f"footprint is {item.package} but the {source} indicates {pkg}",
                    item,
                    "footprint" if source != "mpn" else "mpn",
                )


def _capacitor_voltage(items: list[BomItem], _: RuleContext) -> Iterable[Finding]:
    for item in items:
        if item.kind != "capacitor" or item.dnp:
            continue
        text = " ".join([item.value, item.description, *item.fields.values()])
        try:
            rated = parse_value(item.value, "capacitor").voltage_rating
        except ValueParseError:
            rated = None
        if rated is None and not re.search(r"\d+(\.\d+)?\s?V\b", text) and not item.mpn:
            yield finding(
                "capacitor.voltage_rating",
                Severity.WARNING,
                "no voltage rating and no MPN - derating cannot be checked",
                item,
                "value",
            )


def _mopp(req: Requirements) -> str:
    if req.power_source == PowerSource.MAINS and req.applied_part in {
        AppliedPart.BF,
        AppliedPart.CF,
    }:
        return "2 MOPP between mains and the applied part"
    return "the means of patient protection required for the applied part (§8.5)"


def _iec_isolation(items: list[BomItem], ctx: RuleContext) -> Iterable[Finding]:
    req = ctx.requirements
    if req.applied_part == AppliedPart.NONE:
        return
    for item in items:
        text = " ".join([item.value, item.mpn, item.description])
        if item.kind == "transformer" or _ISOLATION_HINT.search(text):
            yield finding(
                "iec60601.isolation_barrier",
                Severity.REVIEW,
                f"part of the isolation barrier of a type {req.applied_part.value} applied part:"
                f" confirm {_mopp(req)} and creepage/clearance",
                item,
                "mpn",
            )


def _iec_patient_connection(items: list[BomItem], ctx: RuleContext) -> Iterable[Finding]:
    req = ctx.requirements
    if req.applied_part == AppliedPart.NONE:
        return
    for item in items:
        if item.kind == "connector" and re.search(
            r"electrode|patient|\bleads?\b(?!-free)|ecg|eeg",
            f"{item.value} {item.description}",
            re.I,
        ):
            extra = " and defibrillation protection" if req.defibrillation_proof else ""
            yield finding(
                "iec60601.patient_connector",
                Severity.REVIEW,
                f"patient connection: confirm patient leakage current limits"
                f" for type {req.applied_part.value}{extra}",
                item,
                "mpn",
            )


def _iec_mains(items: list[BomItem], ctx: RuleContext) -> Iterable[Finding]:
    if ctx.requirements.power_source != PowerSource.MAINS:
        return
    if not any(i.kind == "fuse" and not i.dnp for i in items):
        yield finding(
            "iec60601.mains_fuse",
            Severity.REVIEW,
            "mains-powered device without a fuse in the BOM: confirm protection",
        )
    for item in items:
        if item.kind == "capacitor" and _Y_CAP.search(f"{item.value} {item.description}"):
            yield finding(
                "iec60601.y_capacitor",
                Severity.REVIEW,
                "Y capacitor: include in the earth/touch leakage current budget",
                item,
                "mpn",
            )


def _iec_battery(items: list[BomItem], ctx: RuleContext) -> Iterable[Finding]:
    for item in items:
        is_batt = item.kind == "battery" or re.search(
            r"\bbatt(ery)?\b|li-?ion|lipo", f"{item.value} {item.description}", re.I
        )
        if is_batt and not item.dnp:
            yield finding(
                "iec60601.battery",
                Severity.REVIEW,
                "battery / battery connector: confirm IEC 62133 certified cells and"
                " protection circuit",
                item,
                "mpn",
            )


CORE_V1 = RulePack(
    PACK_ID,
    PACK_VERSION,
    (
        Rule("schema.valid", Severity.ERROR, "BOM line matches the JSON Schema", _schema_valid),
        Rule(
            "refdes.unique", Severity.ERROR, "Each designator on exactly one line", _refdes_unique
        ),
        Rule(
            "quantity.matches_refdes",
            Severity.ERROR,
            "Quantity equals designator count",
            _quantity_matches,
        ),
        Rule(
            "footprint.present", Severity.ERROR, "Fitted parts have a footprint", _footprint_present
        ),
        Rule(
            "mpn.present", Severity.WARNING, "Fitted parts have MPN and manufacturer", _mpn_present
        ),
        Rule(
            "value.parsable",
            Severity.ERROR,
            "Passive values are valid and in range",
            _value_parsable,
        ),
        Rule(
            "footprint.package_match",
            Severity.ERROR,
            "Footprint package agrees with MPN / value / description",
            _package_consistent,
        ),
        Rule(
            "capacitor.voltage_rating",
            Severity.WARNING,
            "Capacitor voltage is known",
            _capacitor_voltage,
        ),
        Rule(
            "iec60601.isolation_barrier",
            Severity.REVIEW,
            "Isolation barrier components",
            _iec_isolation,
            ("IEC 60601-1:2005+A2:2020 §8.5, §8.8, §8.9",),
        ),
        Rule(
            "iec60601.patient_connector",
            Severity.REVIEW,
            "Patient connections",
            _iec_patient_connection,
            ("IEC 60601-1 §8.7 (leakage), §8.5.5 (defibrillation)",),
        ),
        Rule(
            "iec60601.mains",
            Severity.REVIEW,
            "Mains protection and Y capacitors",
            _iec_mains,
            ("IEC 60601-1 §8.11.5 (fuses), §8.7 (leakage)",),
        ),
        Rule(
            "iec60601.battery",
            Severity.REVIEW,
            "Batteries",
            _iec_battery,
            ("IEC 60601-1 §15.4.3, IEC 62133-2",),
        ),
    ),
)
