"""Structured outputs of the agents (JSON Schema is sent to the model as response_format).

Every agent answers with JSON validated by these models; a response that does not validate
is retried once with the validation error as feedback (``AgentLLM.structured``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Plan(_Out):
    steps: list[str] = Field(default_factory=list)
    notes: str = ""


class ExtractedComponent(_Out):
    refdes: str
    value: str = ""
    footprint: str = ""
    mpn: str = ""
    manufacturer: str = ""
    description: str = ""
    dnp: bool = False


class ExtractedComponents(_Out):
    components: list[ExtractedComponent]


class GroupedLine(_Out):
    refdes: list[str] = Field(min_length=1)
    quantity: int = Field(default=0, ge=0, description="number of parts on the line")
    kind: str = "other"
    value: str = ""
    value_normalized: str | None = None
    footprint: str = ""
    package: str | None = None
    mpn: str = ""
    manufacturer: str = ""
    description: str = ""
    dnp: bool = False


class GroupedBom(_Out):
    lines: list[GroupedLine]


class PartSelection(_Out):
    mpn: str = ""
    manufacturer: str = ""
    description: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    cited_chunks: list[str] = Field(
        default_factory=list, description="ids of the knowledge-base excerpts used"
    )
    rationale: str = ""


class ValidationIssue(_Out):
    refdes: list[str] = Field(default_factory=list)
    field: str | None = None
    severity: Literal["error", "warning", "review", "info"] = "warning"
    message: str
    reselect: bool = Field(default=False, description="true if the part should be selected again")


class ValidationVerdict(_Out):
    issues: list[ValidationIssue] = Field(default_factory=list)


class RepairResult(_Out):
    mpn: str = ""
    manufacturer: str = ""
    footprint: str | None = None
    rationale: str = ""
    cited_chunks: list[str] = Field(default_factory=list)
    give_up: bool = Field(
        default=False, description="true if no valid part can be found - human review needed"
    )
