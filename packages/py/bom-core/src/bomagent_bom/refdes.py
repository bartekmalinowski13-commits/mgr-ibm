"""Reference designators: natural ordering, kinds, compact ranges."""

from __future__ import annotations

import re
from collections.abc import Iterable

_REF = re.compile(r"^(?P<prefix>[A-Za-z_#]+)(?P<num>\d+)(?P<suffix>[A-Za-z]*)$")

# IEEE 315 / common EDA practice. Longest prefix wins (e.g. "FB" before "F").
PREFIX_KIND: dict[str, str] = {
    "R": "resistor",
    "RN": "resistor_network",
    "RV": "potentiometer",
    "VR": "potentiometer",
    "C": "capacitor",
    "L": "inductor",
    "FB": "ferrite_bead",
    "D": "diode",
    "LED": "led",
    "Q": "transistor",
    "U": "ic",
    "IC": "ic",
    "J": "connector",
    "P": "connector",
    "CN": "connector",
    "X": "crystal",
    "Y": "crystal",
    "F": "fuse",
    "SW": "switch",
    "S": "switch",
    "K": "relay",
    "T": "transformer",
    "TP": "test_point",
    "BT": "battery",
    "H": "mechanical",
    "MH": "mechanical",
    "MP": "mechanical",  # mechanical part (drawing BOMs, DXF)
    "JP": "jumper",
    "LS": "speaker",
    "BZ": "buzzer",
    "M": "motor",
}


def split_refdes(ref: str) -> tuple[str, int, str]:
    m = _REF.match(ref.strip())
    if not m:
        return (ref.strip(), 0, "")
    return (m["prefix"].upper(), int(m["num"]), m["suffix"])


def refdes_prefix(ref: str) -> str:
    return split_refdes(ref)[0]


def kind_of(ref: str) -> str:
    """Component kind from the designator prefix (exact match, else ``other``)."""
    return PREFIX_KIND.get(refdes_prefix(ref), "other")


def natural_key(ref: str) -> tuple[str, int, str]:
    return split_refdes(ref)


def sort_refdes(refs: Iterable[str]) -> list[str]:
    return sorted(set(refs), key=natural_key)


def compress(refs: Iterable[str]) -> str:
    """``R1, R2, R3, R5`` -> ``R1-R3, R5`` (display only)."""
    ordered = sort_refdes(refs)
    out: list[str] = []
    i = 0
    while i < len(ordered):
        p, _n, s = split_refdes(ordered[i])
        j = i
        while j + 1 < len(ordered):
            p2, n2, s2 = split_refdes(ordered[j + 1])
            if p2 == p and s2 == s == "" and n2 == split_refdes(ordered[j])[1] + 1:
                j += 1
            else:
                break
        out.append(ordered[i] if j - i < 2 else f"{ordered[i]}-{ordered[j]}")
        if 0 < j - i < 2:
            out.extend(ordered[i + 1 : j + 1])
        i = j + 1
    return ", ".join(out)
