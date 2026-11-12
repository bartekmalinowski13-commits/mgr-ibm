"""Deterministic normalisation and grouping of components into BOM lines.

This is the rule-based core of variant B (and the reference implementation the LLM-only
variant A is compared against). Identical parts - same kind, normalised value, footprint,
MPN, manufacturer and DNP state - become one line with natural-sorted designators.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from bomagent_bom import __version__
from bomagent_bom.model import BomItem, Component, ParsedDesign, Provenance
from bomagent_bom.packages import (
    package_from_footprint,
    package_from_part_number,
    package_from_text,
)
from bomagent_bom.refdes import natural_key
from bomagent_bom.values import ValueParseError, format_quantity, parse_value

MPN_FIELDS = (
    "MPN",
    "Manufacturer Part Number",
    "Manufacturer_Part_Number",
    "MFR PN",
    "MFN PN",
    "Mfr. Part #",
    "MFR_PN",
    "PartNumber",
    "Part Number",
    "MP",
)
MANUFACTURER_FIELDS = ("Manufacturer", "MFR", "Mfr", "Manufacturer_Name", "MF")
DESCRIPTION_FIELDS = ("Description", "Desc")
PASSIVE_KINDS = frozenset({"resistor", "capacitor", "inductor"})

GROUP_RULE = "bom.normalize_group"
GROUP_PACK = "bom-core"


@dataclass(frozen=True, slots=True)
class _Key:
    kind: str
    value: str
    footprint: str
    mpn: str
    manufacturer: str
    dnp: bool


def describe(c: Component) -> dict[str, object]:
    """Normalised attributes of one component (no grouping)."""
    kind = c.kind
    mpn = c.field(*MPN_FIELDS)
    manufacturer = c.field(*MANUFACTURER_FIELDS)
    value_norm: str | None = None
    rating = ""
    if kind in PASSIVE_KINDS:
        try:
            parsed = parse_value(c.value, kind)
        except ValueParseError:
            parsed = None
        if parsed is not None:
            value_norm = format_quantity(parsed.quantity)
            # ratings and attributes are part of the identity of a part: 100n/16V and
            # 100n/50V X7R must not be merged into one line
            rating = "|".join(
                [
                    format_quantity(parsed.voltage_rating) if parsed.voltage_rating else "",
                    str(parsed.tolerance_percent or ""),
                    *sorted(x.casefold() for x in parsed.extra),
                ]
            )
    package = (
        package_from_footprint(c.footprint)
        or package_from_part_number(mpn)
        or package_from_text(c.value)
    )
    return {
        "kind": kind,
        "mpn": mpn,
        "manufacturer": manufacturer,
        "description": c.field(*DESCRIPTION_FIELDS),
        "value_normalized": value_norm,
        "rating": rating,
        "package": package,
    }


def group_components(design: ParsedDesign) -> list[BomItem]:
    groups: dict[_Key, list[Component]] = defaultdict(list)
    attrs: dict[_Key, dict[str, object]] = {}
    for c in design.bom_components():
        d = describe(c)
        key = _Key(
            kind=str(d["kind"]),
            value=f"{d['value_normalized'] or c.value.strip().casefold()}#{d['rating']}",
            footprint=c.footprint.strip(),
            mpn=str(d["mpn"]).upper(),
            manufacturer=str(d["manufacturer"]).casefold(),
            dnp=c.dnp,
        )
        groups[key].append(c)
        attrs.setdefault(key, d | {"value": c.value.strip(), "footprint": c.footprint.strip()})

    parser_prov = Provenance.from_parser(design.source_format)
    rule_prov = Provenance.from_rule(
        GROUP_RULE, GROUP_PACK, __version__, "grouped by kind, value, footprint, MPN, DNP"
    )
    ordered = sorted(groups.items(), key=lambda kv: natural_key(min(c.refdes for c in kv[1])))
    items: list[BomItem] = []
    for line, (key, comps) in enumerate(ordered, start=1):
        a = attrs[key]
        refs = [c.refdes for c in comps]
        provenance = {
            "item": rule_prov,
            "quantity": rule_prov,
            "value": parser_prov,
            "footprint": parser_prov,
        }
        if a["value_normalized"]:
            provenance["value_normalized"] = rule_prov
        if a["package"]:
            provenance["package"] = rule_prov
        if a["mpn"]:
            provenance["mpn"] = parser_prov
        if a["manufacturer"]:
            provenance["manufacturer"] = parser_prov
        items.append(
            BomItem(
                line=line,
                refdes=refs,
                quantity=len(refs),
                kind=key.kind,
                value=str(a["value"]),
                value_normalized=a["value_normalized"],  # type: ignore[arg-type]
                footprint=str(a["footprint"]),
                package=a["package"],  # type: ignore[arg-type]
                manufacturer=str(a["manufacturer"]),
                mpn=str(a["mpn"]),
                description=str(a["description"]),
                dnp=key.dnp,
                provenance=provenance,
            )
        )
    return items


def renumber(items: list[BomItem]) -> list[BomItem]:
    """Re-sort by first designator and renumber lines 1..n."""
    ordered = sorted(items, key=lambda i: natural_key(i.refdes[0]))
    return [i.model_copy(update={"line": n}) for n, i in enumerate(ordered, start=1)]
