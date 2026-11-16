"""Evaluation dataset hygiene (TH-03).

Two roles, never pooled in headline statistics:

* ``control`` - self-authored designs; they allow controlled error injection;
* ``real`` - open designs from other people. Every one needs a ``SOURCE.md`` with URL, pinned
  commit, licence and retrieval date, and a reference BOM built by **two distinct verifiers**
  (their agreement is reported with ``bomagent_eval.agreement``).

Designs are stratified by size so results are not dominated by one class.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from bomagent_eval.reference import load_reference


class DatasetError(ValueError):
    """A dataset entry does not meet the rules for use in the experiment."""


class Stratum(StrEnum):
    SMALL = "small"  # < 40 components
    MEDIUM = "medium"  # 40-150
    LARGE = "large"  # > 150


def stratum_of(components: int) -> Stratum:
    if components < 1:
        raise ValueError("a design has at least one component")
    if components < 40:
        return Stratum.SMALL
    return Stratum.MEDIUM if components <= 150 else Stratum.LARGE


@dataclass(frozen=True)
class SourceInfo:
    url: str
    commit: str
    licence: str
    retrieved: str
    verifiers: list[str]


_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _field(text: str, name: str) -> str | None:
    m = re.search(rf"^[-*]\s*{name}\s*:\s*(.+?)\s*$", text, re.IGNORECASE | re.MULTILINE)
    return m.group(1) if m else None


def parse_source_md(text: str) -> SourceInfo:
    """Parse the ``- Key: value`` list of a dataset ``SOURCE.md``."""
    values = {k: _field(text, k) for k in ("URL", "Commit", "Licence", "Retrieved")}
    for key, value in values.items():
        if not value:
            raise DatasetError(f"SOURCE.md: missing {key}")
    commit, retrieved = values["Commit"] or "", values["Retrieved"] or ""
    if not _COMMIT.match(commit):
        raise DatasetError(f"SOURCE.md: Commit must be a pinned hash, got {commit!r}")
    if not _DATE.match(retrieved):
        raise DatasetError(f"SOURCE.md: Retrieved must be YYYY-MM-DD, got {retrieved!r}")
    verifiers = [v for n in (1, 2) if (v := _field(text, f"Verifier {n}"))]
    return SourceInfo(values["URL"] or "", commit, values["Licence"] or "", retrieved, verifiers)


@dataclass(frozen=True)
class DatasetEntry:
    path: Path
    role: str
    stratum: Stratum
    components: int
    source: SourceInfo | None


def validate_dataset(directory: Path, *, role: Literal["real", "control"]) -> DatasetEntry:
    """Check one design directory (``reference_bom.csv`` and, for real designs, ``SOURCE.md``)."""
    reference = directory / "reference_bom.csv"
    if not reference.is_file():
        raise DatasetError(f"{directory.name}: reference_bom.csv missing")
    components = sum(len(i.refdes) for i in load_reference(reference) if not i.dnp)
    source: SourceInfo | None = None
    if role == "real":
        source_file = directory / "SOURCE.md"
        if not source_file.is_file():
            raise DatasetError(f"{directory.name}: SOURCE.md missing")
        source = parse_source_md(source_file.read_text(encoding="utf-8"))
        if len(source.verifiers) < 2:
            raise DatasetError(f"{directory.name}: a real design needs two verifiers")
        if len({v.casefold() for v in source.verifiers}) < 2:
            raise DatasetError(f"{directory.name}: the two verifiers must be distinct people")
    return DatasetEntry(directory, role, stratum_of(max(components, 1)), components, source)
