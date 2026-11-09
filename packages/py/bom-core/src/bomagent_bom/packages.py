"""Package (case) codes from footprints, part numbers and descriptions.

Used by the deterministic rule ``footprint.package_match`` and by grouping. Only
well-established conventions are encoded (KiCad library naming, imperial chip codes,
manufacturer series codes for passives); unknown inputs return ``None`` rather than a
guess.
"""

from __future__ import annotations

import re

CHIP_SIZES = ("01005", "0201", "0402", "0603", "0805", "1206", "1210", "1812", "2010", "2512")
# metric chip code -> imperial
METRIC_TO_IMPERIAL = {
    "0402": "01005",
    "0603": "0201",
    "1005": "0402",
    "1608": "0603",
    "2012": "0805",
    "3216": "1206",
    "3225": "1210",
    "4532": "1812",
    "5025": "2010",
    "6332": "2512",
}

_KICAD_CHIP = re.compile(r"_(?P<imp>\d{4,5})_(?P<metric>\d{4})Metric")
_IC_PACKAGE = re.compile(
    r"(?P<pkg>(?:SOIC|SOP|SSOP|TSSOP|MSOP|QFN|DFN|VQFN|WQFN|TQFP|LQFP|QFP|BGA|WLCSP|"
    r"SOT|TO|SOD|SMA|SMB|SMC|DIP|PDIP|DPAK|D2PAK|LGA|PLCC)-?\d*(?:-\d+)?)",
    re.IGNORECASE,
)

# manufacturer series codes encoding the chip size (resistors and MLCCs)
_IMPERIAL = "01005|0201|0402|0603|0805|1206|1210|2010|2512"
_SERIES_PATTERNS: tuple[tuple[re.Pattern[str], dict[str, str]], ...] = (
    # Yageo RC0603..., KEMET C0603..., Vishay CRCW0603..., Bourns CR0603...
    (re.compile(rf"^(?:RC|RT|AC|CRCW|CR|C|ERA|RMCF)(?P<code>{_IMPERIAL})"), {}),
    # Murata GRM155 / GRM188 / GRM21B / GRM31C
    (
        re.compile(r"^GR[MJ](?P<code>03|15|18|21|31|32|43)"),
        {
            "03": "0201",
            "15": "0402",
            "18": "0603",
            "21": "0805",
            "31": "1206",
            "32": "1210",
            "43": "1812",
        },
    ),
    # Samsung CL05 / CL10 / CL21 / CL31
    (
        re.compile(r"^CL(?P<code>03|05|10|21|31|32)"),
        {"03": "0201", "05": "0402", "10": "0603", "21": "0805", "31": "1206", "32": "1210"},
    ),
    # TDK C1005 / C1608 / C2012 / C3216 (metric; C0603 is left out: it collides with
    # KEMET's imperial C0603 and is matched by the first pattern)
    (
        re.compile(r"^C(?P<code>1005|1608|2012|3216|3225)"),
        {"1005": "0402", "1608": "0603", "2012": "0805", "3216": "1206", "3225": "1210"},
    ),
    # Panasonic ERJ-1G/2/3/6/8 (resistors)
    (
        re.compile(r"^ERJ-?(?P<code>1G|2|3|6|8)"),
        {"1G": "0201", "2": "0402", "3": "0603", "6": "0805", "8": "1206"},
    ),
)


def package_from_footprint(footprint: str) -> str | None:
    """``R_0603_1608Metric`` -> ``0603``; ``Package_SO:SOIC-8_3.9x4.9mm`` -> ``SOIC-8``."""
    if not footprint:
        return None
    name = footprint.split(":", 1)[-1]
    m = _KICAD_CHIP.search(name)
    if m:
        return m["imp"]
    for size in CHIP_SIZES:
        if re.search(rf"(?<!\d){size}(?!\d)", name):
            return size
    m = _IC_PACKAGE.search(name)
    if m:
        return m["pkg"].upper()
    return None


def package_from_part_number(mpn: str) -> str | None:
    """Chip size encoded in common passive part numbers, else ``None``."""
    text = mpn.strip().upper()
    if not text:
        return None
    for pattern, table in _SERIES_PATTERNS:
        m = pattern.match(text)
        if m:
            code = m["code"]
            return table.get(code, code) if table else code
    return None


def package_from_text(text: str) -> str | None:
    """Explicit chip size mentioned in free text (value/description), e.g. ``100n 0402``."""
    for size in CHIP_SIZES:
        if re.search(rf"(?<![\d.]){size}(?![\d.])", text):
            return size
    return None
