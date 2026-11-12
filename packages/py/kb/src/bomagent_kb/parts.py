"""Conservative extraction of manufacturer part numbers from datasheet text.

Only tokens on lines that talk about ordering / part numbers are taken, and a token must
look like an MPN (letters and digits, 6-40 chars, at least two digits). This feeds the
part catalogue used to detect hallucinated MPNs, so precision matters more than recall.
"""

from __future__ import annotations

import re

_CONTEXT = re.compile(
    r"(ordering|order code|order number|part number|part no|mpn|orderable|numer katalogowy)",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Z0-9][A-Z0-9\-+/#.()]{4,38}[A-Z0-9)+#])(?![A-Za-z0-9])")
_PACKAGE = re.compile(
    r"^(SOT|SOIC|SOP|SSOP|TSSOP|MSOP|VSSOP|QFN|DFN|TQFP|LQFP|SOD|LFCSP|DSBGA|SC70|TO|DIP|BGA)-?\d",
    re.IGNORECASE,
)
_STOP = {"ORDERING", "INFORMATION", "PACKAGE", "NUMBER", "MARKING", "QUANTITY", "TEMPERATURE"}


_HEADING = re.compile(r"^\s*(#{1,6}\s|[A-Z][A-Z0-9 /&()\-]{3,60}$)")


def extract_part_numbers(text: str) -> list[str]:
    """Tokens from lines that mention ordering/part numbers, or that sit in a section whose
    heading does (e.g. everything under "Ordering information")."""
    found: list[str] = []
    seen: set[str] = set()
    in_section = False
    for line in text.splitlines():
        if _HEADING.match(line):
            in_section = bool(_CONTEXT.search(line))
            continue
        if not (in_section or _CONTEXT.search(line)):
            continue
        for m in _TOKEN.finditer(line):
            token = m.group(1).rstrip(".")
            letters = sum(ch.isalpha() for ch in token)
            digits = sum(ch.isdigit() for ch in token)
            if digits < 2 or letters < 1 or token.upper() in _STOP or _PACKAGE.match(token):
                continue
            if token not in seen:
                seen.add(token)
                found.append(token)
    return found
