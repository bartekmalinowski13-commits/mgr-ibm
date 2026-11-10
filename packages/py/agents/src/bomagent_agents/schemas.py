"""Structured-output schemas of the agents (JSON Schema is sent to the gateway)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _S(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MpnChoice(_S):
    mpn: str = ""
    manufacturer: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=1000)
    citation_chunk_ids: list[str] = Field(default_factory=list)


class LineOut(_S):
    refdes: list[str]
    quantity: int | None = None
    value: str = ""
    footprint: str = ""
    mpn: str = ""
    manufacturer: str = ""
    dnp: bool = False


class GroupedLines(_S):
    lines: list[LineOut]


class FindingOut(_S):
    refdes: list[str] = Field(default_factory=list)
    field: str | None = None
    severity: Literal["error", "warning", "review", "info"] = "warning"
    message: str = ""


class ValidationOut(_S):
    findings: list[FindingOut]


class Fix(_S):
    line: int
    field: Literal["value", "footprint", "mpn", "manufacturer", "quantity", "refdes"]
    new_value: str
    reason: str = ""


class RepairOut(_S):
    fixes: list[Fix]


def schema_of(model: type[BaseModel]) -> dict[str, object]:
    return model.model_json_schema()
