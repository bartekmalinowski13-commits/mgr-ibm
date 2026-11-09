"""Normalisation of electronic component values and units.

Handles the notations engineers actually type into schematics:

* SI prefixes with or without unit: ``10k``, ``10 kΩ``, ``10kohm``, ``2.2M``
* RKM / IEC 60062 code with the multiplier as decimal separator: ``4k7``, ``1R0``,
  ``0R``, ``4u7``, ``2n2``, ``1M5``
* ``µ`` / ``μ`` / ``u`` for micro; ``R``/``E`` as the ohm marker
* trailing attributes separated by space, ``/`` or ``,``: ``100n/50V``, ``10u 16V X5R``,
  ``10k 1%`` - the voltage rating and tolerance are extracted, the rest is ignored

Values are kept as :class:`~decimal.Decimal` (exact, no float rounding) in base units
(Ω, F, H, V, A, Hz). ``format_quantity`` renders the canonical engineering form used in
BOMs (``4.7 kΩ``) and ``parse_value(format_quantity(q))`` round-trips.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

Unit = Literal["Ω", "F", "H", "V", "A", "Hz", "W"]

PREFIXES: dict[str, int] = {
    "p": -12,
    "n": -9,
    "u": -6,
    "µ": -6,
    "μ": -6,
    "m": -3,
    "": 0,
    "k": 3,
    "K": 3,
    "M": 6,
    "G": 9,
}
_CANONICAL_PREFIX: dict[int, str] = {
    -12: "p",
    -9: "n",
    -6: "µ",
    -3: "m",
    0: "",
    3: "k",
    6: "M",
    9: "G",
}

_UNIT_ALIASES: dict[str, Unit] = {
    "ω": "Ω",
    "Ω": "Ω",
    "ohm": "Ω",
    "ohms": "Ω",
    "r": "Ω",
    "f": "F",
    "h": "H",
    "v": "V",
    "a": "A",
    "hz": "Hz",
    "w": "W",
}

# default unit for a bare number / RKM code given the component kind
KIND_UNIT: dict[str, Unit] = {"resistor": "Ω", "capacitor": "F", "inductor": "H"}


class ValueParseError(ValueError):
    """The text is not a recognisable component value."""


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal
    unit: Unit

    def __str__(self) -> str:
        return format_quantity(self)


@dataclass(frozen=True, slots=True)
class ParsedValue:
    """Main value plus attributes found in the same text."""

    quantity: Quantity
    voltage_rating: Quantity | None = None
    tolerance_percent: Decimal | None = None
    extra: tuple[str, ...] = ()


# 4k7, 1R0, 0R5, 4u7, 2n2, 1M5, 4K7, 4E7 (E = ohm marker in some libraries)
_RKM = re.compile(r"^(?P<int>\d+)(?P<mark>[pnuµμmkKMGRrE])(?P<frac>\d+)(?P<unit>[A-Za-zΩω]*)$")
# 4.7k, 10, 100n, 2.2 M, 10 kΩ, 0.1uF, 100nF, 10kohm, 1R
_PLAIN = re.compile(
    r"^(?P<num>\d+(?:[.,]\d+)?|[.,]\d+)\s*(?P<prefix>[pnuµμmkKMG]?)\s*(?P<unit>[A-Za-zΩω]*)$"
)
# R10 = 0.10 Ω, R47 = 0.47 Ω (RKM with leading ohm marker)
_RKM_LEADING_R = re.compile(r"^[Rr](?P<frac>\d+)$")
_TOLERANCE = re.compile(r"^±?(?P<tol>\d+(?:[.,]\d+)?)\s*%$")
# attribute separators: whitespace, "/", ";" and "," unless it is a decimal comma (0,1uF)
_SPLIT = re.compile(r"[\s/;]+|,\s*(?!\d)|(?<!\d),\s*")
# "10 kΩ" / "2.2 kOhm" / "100 nF": join a number with the unit that follows it
_SPACED_UNIT = re.compile(
    r"(\d)\s+([pnuµμmkKMG]?(?:Ω|ω|[Oo]hms?|OHMS?|F|H|V|A|Hz|W)|[pnuµμmkKMG])(?=$|[\s/;,])"
)


def _to_decimal(text: str) -> Decimal:
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation as exc:  # pragma: no cover - regex guarantees digits
        raise ValueParseError(text) from exc


def _unit(text: str, default: Unit | None) -> Unit | None:
    if not text:
        return default
    unit = _UNIT_ALIASES.get(text.lower()) or _UNIT_ALIASES.get(text)
    if unit is None:
        raise ValueParseError(f"unknown unit {text!r}")
    return unit


def parse_quantity(text: str, default_unit: Unit | None = None) -> Quantity:
    """Parse a single token like ``4k7``, ``100nF`` or ``10 kΩ``."""
    raw = text.strip()
    if not raw:
        raise ValueParseError("empty value")
    m = _RKM_LEADING_R.match(raw)
    if m:
        return Quantity(_to_decimal(f"0.{m['frac']}"), "Ω")
    m = _RKM.match(raw)
    if m:
        mark = m["mark"]
        unit_default: Unit | None
        if mark in {"R", "r", "E"}:
            exp, unit_default = 0, "Ω"
        else:
            exp, unit_default = PREFIXES[mark], default_unit
        number = _to_decimal(f"{m['int']}.{m['frac']}")
        unit = _unit(m["unit"], unit_default)
        if unit is None:
            raise ValueParseError(f"cannot infer unit of {raw!r}")
        return Quantity(number.scaleb(exp), unit)
    m = _PLAIN.match(raw)
    if m:
        prefix, unit_text = m["prefix"], m["unit"]
        # "1R" / "10R" / "1m" (milli without unit) are ambiguous: R means ohm, bare "m"
        # with a default unit is milli.
        if unit_text in {"R", "r", "E"} and not prefix:
            unit_text = "ohm"
        # "100M" with no unit -> mega (not milli); "10m" -> milli
        unit = _unit(unit_text, default_unit)
        if unit is None:
            raise ValueParseError(f"cannot infer unit of {raw!r}")
        number = _to_decimal(m["num"])
        return Quantity(number.scaleb(PREFIXES[prefix]), unit)
    raise ValueParseError(f"unrecognised value {raw!r}")


def parse_value(text: str, kind: str | None = None) -> ParsedValue:
    """Parse a schematic value field; ``kind`` (resistor/capacitor/inductor) sets the
    default unit for bare numbers. Attributes (voltage, tolerance) are extracted."""
    default = KIND_UNIT.get(kind or "")
    joined = _SPACED_UNIT.sub(r"\1\2", text.strip())
    tokens = [t for t in _SPLIT.split(joined) if t]
    if not tokens:
        raise ValueParseError("empty value")
    main = parse_quantity(tokens[0], default)
    voltage: Quantity | None = None
    tolerance: Decimal | None = None
    extra: list[str] = []
    for token in tokens[1:]:
        tol = _TOLERANCE.match(token)
        if tol:
            tolerance = _to_decimal(tol["tol"])
            continue
        try:
            q = parse_quantity(token)
        except ValueParseError:
            extra.append(token)
            continue
        if q.unit == "V" and voltage is None:
            voltage = q
        elif main.unit == q.unit and main.value == q.value:
            continue
        else:
            extra.append(token)
    return ParsedValue(main, voltage, tolerance, tuple(extra))


def format_quantity(q: Quantity) -> str:
    """Canonical engineering notation: ``4.7 kΩ``, ``100 nF``, ``0 Ω``."""
    if q.value == 0:
        return f"0 {q.unit}"
    exp = q.value.adjusted()
    eng = max(-12, min(9, (exp // 3) * 3))
    mantissa = q.value.scaleb(-eng).normalize()
    # avoid scientific notation like 1E+1 from normalize()
    text = format(mantissa, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text} {_CANONICAL_PREFIX[eng]}{q.unit}"


def normalize_value(text: str, kind: str | None = None) -> str | None:
    """Canonical string of the main value, or ``None`` if it is not a numeric value
    (e.g. an IC part name such as ``AD8232``)."""
    try:
        return format_quantity(parse_value(text, kind).quantity)
    except ValueParseError:
        return None


def values_equivalent(a: str, b: str, kind: str | None = None) -> bool:
    """``4k7`` == ``4.7k`` == ``4700 Ω``; non-numeric values compare case-insensitively."""
    na, nb = normalize_value(a, kind), normalize_value(b, kind)
    if na is not None and nb is not None:
        return na == nb
    return a.strip().casefold() == b.strip().casefold()
