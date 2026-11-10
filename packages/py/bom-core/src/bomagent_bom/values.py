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


# 4k7, 1R0, 0R5, 4u7, 2n2, 1M5, 4K7, 6V3 (6.3 V)
_RKM = re.compile(r"^(?P<int>\d+)(?P<mark>[pnuµμmkKMGRrV])(?P<frac>\d+)(?P<unit>[A-Za-zΩωΩ]*)$")
# R10 = 0.10 (Ω for resistors), R47
_RKM_LEADING_R = re.compile(r"^[Rr](?P<frac>\d+)$")
# number followed by an optional prefix+unit suffix: 4.7k, 10, 100nF, 10kΩ, 0.1UF, 2.2MEG
_PLAIN = re.compile(r"^(?P<num>\d+(?:[.,]\d+)?|[.,]\d+)(?P<suffix>[A-Za-zµμΩωΩ]*)$")
# 1,000 / 2,200 - thousands separator or decimal comma? refuse to guess
_THOUSANDS = re.compile(r"^\d{1,3},\d{3}(?!\d)")
_TOLERANCE = re.compile(r"^±?(?P<tol>\d+(?:[.,]\d+)?)%$")
# attribute separators: whitespace, "/", ";" and "," unless it is a decimal comma (0,1uF)
_SPLIT = re.compile(r"[\s/;]+|,\s*(?!\d)|(?<!\d),\s*")
# "10 kΩ" / "2.2 kOhm" / "100 nF" / "4.7 UF" / "10 MEG": join a number with its unit
_SPACED_UNIT = re.compile(
    r"(\d)\s+((?:MEG|Meg|meg|[pPnNuUµμmMkKgG])?(?:Ω|ω|Ω|[Oo]hms?|OHMS?|[FfHhVvAaWw]|Hz|HZ|FD|fd)?)"
    r"(?=$|[\s/;,])"
)
_DIELECTRIC = re.compile(r"^(X5R|X7R|X6S|X7S|X8R|C0G|COG|NP0|NPO|Y5V|Z5U|X7T)$", re.IGNORECASE)
_RKM_R_UNIT: dict[str, tuple[Unit, int]] = {
    # the R marker is the decimal point in the kind's customary unit
    "resistor": ("Ω", 0),
    "capacitor": ("F", -12),  # 4R7 = 4.7 pF
    "inductor": ("H", -6),  # 4R7 = 4.7 µH
}
# suffix (lower-cased) -> (exponent, unit or None for "kind's default unit")
_SUFFIXES: dict[str, tuple[int, Unit | None]] = {}
_UNIT_WORDS: tuple[tuple[str, Unit | None], ...] = (
    ("", None),
    ("f", "F"),
    ("fd", "F"),
    ("h", "H"),
    ("v", "V"),
    ("a", "A"),
    ("w", "W"),
    ("hz", "Hz"),
    ("ohm", "Ω"),
    ("ohms", "Ω"),
    ("ω", "Ω"),
    ("\u2126", "Ω"),
    ("r", "Ω"),
)
for _p, _e in (
    ("p", -12),
    ("n", -9),
    ("u", -6),
    ("µ", -6),
    ("μ", -6),
    ("", 0),
    ("k", 3),
    ("meg", 6),
    ("g", 9),
):
    for _word, _base in _UNIT_WORDS:
        _SUFFIXES.setdefault(_p + _word, (_e, _base))
_SUFFIXES["mfd"] = (-6, "F")  # legacy US notation: MFD = microfarad


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


def _suffix(suffix: str, default_unit: Unit | None, raw: str) -> tuple[int, Unit]:
    """Resolve prefix+unit case-insensitively, except the M/m distinction, which is
    kept: ``M`` = mega, ``m`` = milli; ``MEG`` = mega, ``MFD`` = microfarad; ``MF`` is
    ambiguous (legacy microfarad vs megafarad) and rejected."""
    if suffix.upper() == "MF" and suffix != "mF":
        raise ValueParseError(f"ambiguous unit {suffix!r} in {raw!r} (write µF)")
    low = suffix.lower()
    if low.startswith("m") and not low.startswith(("meg", "mfd")):
        exp = 6 if suffix[0] == "M" else -3
        entry = _SUFFIXES.get(low[1:])
        if entry is None or entry[0] != 0:
            raise ValueParseError(f"unknown unit {suffix!r} in {raw!r}")
        return exp, entry[1] or _require(default_unit, raw)
    entry = _SUFFIXES.get(low)
    if entry is None:
        raise ValueParseError(f"unknown unit {suffix!r} in {raw!r}")
    exp, unit = entry
    return exp, unit or _require(default_unit, raw)


def _require(unit: Unit | None, raw: str) -> Unit:
    if unit is None:
        raise ValueParseError(f"cannot infer unit of {raw!r}")
    return unit


def parse_quantity(
    text: str, default_unit: Unit | None = None, kind: str | None = None
) -> Quantity:
    """Parse a single token like ``4k7``, ``100nF``, ``10 kΩ`` or ``4.7UF``."""
    raw = _SPACED_UNIT.sub(r"\1\2", text.strip())
    if not raw:
        raise ValueParseError("empty value")
    if _THOUSANDS.match(raw):
        raise ValueParseError(f"ambiguous separator in {raw!r} (thousands or decimal comma?)")
    m = _RKM_LEADING_R.match(raw)
    if m:
        unit, exp = _RKM_R_UNIT.get(kind or "", ("Ω", 0))
        return Quantity(_to_decimal(f"0.{m['frac']}").scaleb(exp), unit)
    m = _RKM.match(raw)
    if m:
        mark = m["mark"]
        number = _to_decimal(f"{m['int']}.{m['frac']}")
        if mark in {"R", "r"}:
            unit_r, exp = _RKM_R_UNIT.get(kind or "", ("Ω", 0))
            if m["unit"]:
                unit_r = _require(_unit(m["unit"], None), raw)
            return Quantity(number.scaleb(exp), unit_r)
        if mark == "V":
            if m["unit"]:
                raise ValueParseError(f"unrecognised value {raw!r}")
            return Quantity(number, "V")
        rkm_unit = _unit(m["unit"], default_unit)
        return Quantity(number.scaleb(PREFIXES[mark]), _require(rkm_unit, raw))
    m = _PLAIN.match(raw)
    if m:
        number = _to_decimal(m["num"])
        exp, unit = (
            _suffix(m["suffix"], default_unit, raw)
            if m["suffix"]
            else (0, _require(default_unit, raw))
        )
        return Quantity(number.scaleb(exp), unit)
    raise ValueParseError(f"unrecognised value {raw!r}")


def _normalise_text(text: str) -> str:
    text = text.strip().replace("+/-", "±").replace("+-", "±")
    text = re.sub(r"(\d)\s+%", r"\1%", text)
    text = re.sub(r"±\s+", "±", text)
    return _SPACED_UNIT.sub(r"\1\2", text)


def parse_value(text: str, kind: str | None = None) -> ParsedValue:
    """Parse a schematic value field; ``kind`` (resistor/capacitor/inductor) sets the
    default unit for bare numbers. Attributes (voltage, tolerance, dielectric) are
    extracted; an unknown word right after a bare number is an error, never ignored."""
    default = KIND_UNIT.get(kind or "")
    tokens = [t for t in _SPLIT.split(_normalise_text(text)) if t]
    if not tokens:
        raise ValueParseError("empty value")
    main = parse_quantity(tokens[0], default, kind)
    bare_number = bool(re.fullmatch(r"\d+(?:[.,]\d+)?", tokens[0]))
    voltage: Quantity | None = None
    tolerance: Decimal | None = None
    extra: list[str] = []
    for i, token in enumerate(tokens[1:]):
        tol = _TOLERANCE.match(token)
        if tol:
            tolerance = _to_decimal(tol["tol"])
            continue
        try:
            q = parse_quantity(token, None, kind)
        except ValueParseError:
            if i == 0 and bare_number and token[:1].isalpha() and not _DIELECTRIC.match(token):
                raise ValueParseError(
                    f"unknown unit {token!r} after a bare number in {text!r}"
                ) from None
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
