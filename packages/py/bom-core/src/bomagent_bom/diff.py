"""Difference between two BOM versions of one run (version history, UX-03).

Lines are matched by their line number: versions of one run only differ by user
corrections, which never renumber lines.
"""

from __future__ import annotations

from pydantic import BaseModel

from bomagent_bom.model import BomItem, BomVersion

COMPARED_FIELDS = (
    "refdes",
    "quantity",
    "kind",
    "value",
    "footprint",
    "package",
    "manufacturer",
    "mpn",
    "description",
    "dnp",
)


class FieldChange(BaseModel):
    field: str
    before: str
    after: str


class LineChange(BaseModel):
    line: int
    refdes: list[str]
    fields: list[FieldChange]


class BomDiff(BaseModel):
    added: list[BomItem]
    removed: list[BomItem]
    changed: list[LineChange]


def _show(value: object) -> str:
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return "" if value is None else str(value)


def diff_versions(old: BomVersion, new: BomVersion) -> BomDiff:
    before = {i.line: i for i in old.items}
    after = {i.line: i for i in new.items}
    changed: list[LineChange] = []
    for line in sorted(before.keys() & after.keys()):
        a, b = before[line], after[line]
        fields = [
            FieldChange(field=f, before=_show(getattr(a, f)), after=_show(getattr(b, f)))
            for f in COMPARED_FIELDS
            if getattr(a, f) != getattr(b, f)
        ]
        if fields:
            changed.append(LineChange(line=line, refdes=b.refdes, fields=fields))
    return BomDiff(
        added=[after[n] for n in sorted(after.keys() - before.keys())],
        removed=[before[n] for n in sorted(before.keys() - after.keys())],
        changed=changed,
    )
