"""One interpretation of "do not populate" markers for every importer.

``parse_dnp(cell, column)`` returns ``True`` (not fitted), ``False`` (fitted) or ``None``
(unrecognised - the importer reports it instead of guessing). ``column`` says whether the
column asks "DNP?" (``dnp``) or "fitted?" (``populate``).
"""

from __future__ import annotations

from typing import Literal

_DNP_TRUE = {
    "dnp",
    "dnf",
    "dni",
    "nf",
    "nm",
    "nc",
    "x",
    "yes",
    "y",
    "true",
    "1",
    "do not populate",
    "do not fit",
    "not fitted",
    "no fit",
    "no-fit",
    "not mounted",
}
_DNP_FALSE = {"", "no", "n", "false", "0", "-", "fit", "fitted", "populate", "mounted"}
_POP_TRUE = {"yes", "y", "true", "1", "fit", "fitted", "populate", "mounted", "x"}
_POP_FALSE = {
    "no",
    "n",
    "false",
    "0",
    "dnp",
    "dnf",
    "dni",
    "nf",
    "not fitted",
    "no fit",
    "do not populate",
}


def parse_dnp(cell: str, column: Literal["dnp", "populate"] = "dnp") -> bool | None:
    value = cell.strip().casefold()
    if column == "dnp":
        if value in _DNP_TRUE:
            return True
        if value in _DNP_FALSE:
            return False
        return None
    if value in _POP_TRUE or value == "":
        return False
    if value in _POP_FALSE:
        return True
    return None
