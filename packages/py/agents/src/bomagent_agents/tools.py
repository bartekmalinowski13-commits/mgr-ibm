"""Read-only CAD tools exposed to agents (variant A reads the design only through these).

The tools are deterministic views of the parser output (``ParsedDesign``); they never
expose file paths or anything outside the current design. Arguments are validated and
results are paged so a large design cannot blow up a single model call.
"""

from __future__ import annotations

from typing import Any

from bomagent_bom.model import ParsedDesign
from bomagent_llm.chat import ToolSpec

PAGE_LIMIT = 50

TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="list_sheets",
        description="List the schematic sheets of the design with their component counts.",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    ToolSpec(
        name="list_components",
        description=(
            "List placed components (one page). Returns reference designator, value, "
            "footprint, symbol fields, DNP and in_bom flags, plus next_offset (null at end)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sheet": {"type": "string", "description": "sheet path, omit for all sheets"},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": PAGE_LIMIT, "default": 50},
            },
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        name="get_component",
        description="Full details of one component by reference designator.",
        parameters={
            "type": "object",
            "properties": {"refdes": {"type": "string"}},
            "required": ["refdes"],
            "additionalProperties": False,
        },
    ),
]


class ToolError(ValueError):
    pass


class CadTools:
    def __init__(self, design: ParsedDesign) -> None:
        self.design = design
        self.calls = 0

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if name == "list_sheets":
            counts: dict[str, int] = {}
            for c in self.design.components:
                counts[c.sheet_path] = counts.get(c.sheet_path, 0) + 1
            return {
                "sheets": [{"path": s, "components": counts.get(s, 0)} for s in self.design.sheets]
            }
        if name == "list_components":
            sheet = arguments.get("sheet")
            offset = int(arguments.get("offset", 0) or 0)
            limit = min(int(arguments.get("limit", PAGE_LIMIT) or PAGE_LIMIT), PAGE_LIMIT)
            if offset < 0 or limit < 1:
                raise ToolError("offset must be >= 0 and limit >= 1")
            comps = [c for c in self.design.components if sheet in (None, "", c.sheet_path)]
            page = comps[offset : offset + limit]
            nxt = offset + limit if offset + limit < len(comps) else None
            return {
                "total": len(comps),
                "next_offset": nxt,
                "components": [self._component(c.refdes) for c in page],
            }
        if name == "get_component":
            return self._component(str(arguments.get("refdes", "")))
        raise ToolError(f"unknown tool {name!r}")

    def _component(self, refdes: str) -> dict[str, Any]:
        for c in self.design.components:
            if c.refdes == refdes:
                return {
                    "refdes": c.refdes,
                    "value": c.value,
                    "footprint": c.footprint,
                    "fields": dict(c.fields),
                    "dnp": c.dnp,
                    "in_bom": c.in_bom,
                    "sheet": c.sheet_path,
                }
        raise ToolError(f"no component {refdes!r}")
