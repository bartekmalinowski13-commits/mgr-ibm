"""Deterministic, versioned BOM validation rule packs."""

from __future__ import annotations

from bomagent_bom.model import BomItem, BomVersion, Requirements
from bomagent_rules.base import Rule, RuleContext, RulePack, ValidationReport, run_pack
from bomagent_rules.core_v1 import CORE_V1

__version__ = "1.0.0"
PACKS: dict[str, RulePack] = {f"{CORE_V1.id}@{CORE_V1.version}": CORE_V1}
DEFAULT_PACK = CORE_V1


def validate(
    bom: BomVersion | list[BomItem], requirements: Requirements | None = None
) -> ValidationReport:
    """Run the default rule pack (``core@1.0.0``)."""
    return run_pack(DEFAULT_PACK, bom, RuleContext(requirements or Requirements()))


__all__ = [
    "CORE_V1",
    "DEFAULT_PACK",
    "PACKS",
    "Rule",
    "RuleContext",
    "RulePack",
    "ValidationReport",
    "run_pack",
    "validate",
]
