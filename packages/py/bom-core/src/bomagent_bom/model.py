"""BOM domain model - the shared contract of variants A and B (ADR-0007).

``ParsedDesign`` (parser output) + ``Requirements`` + run configuration go into a variant
runtime; a ``BomVersion`` comes out. Every BOM line carries **provenance** per field: which
rule (with rule-pack version), which agent (model, prompt version, cited KB chunks), the
parser, or which user decided the value (ADR-0011, UX "panel pochodzenia").
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bomagent_bom.refdes import kind_of, sort_refdes

SCHEMA_VERSION = "1.0.0"

RefDes = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_#]+\d+[A-Za-z]*$")]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, str_strip_whitespace=True)


# --------------------------------------------------------------------------- input side
class SourceFile(_Model):
    name: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class Component(_Model):
    """One placed part instance as read from the design (before grouping)."""

    refdes: RefDes
    value: str = ""
    footprint: str = ""
    lib_id: str = ""
    fields: dict[str, str] = Field(default_factory=dict)
    dnp: bool = False
    in_bom: bool = True
    sheet_path: str = "/"

    @property
    def kind(self) -> str:
        return kind_of(self.refdes)

    def field(self, *names: str) -> str:
        """First non-empty field among ``names`` (case-insensitive)."""
        lowered = {k.casefold(): v for k, v in self.fields.items()}
        for name in names:
            value = lowered.get(name.casefold(), "").strip()
            if value and value != "~":
                return value
        return ""


class ParsedDesign(_Model):
    """Output of a format parser (FORMATS.md: ``parse(file) -> ParsedDesign``)."""

    design_name: str
    source_format: str
    components: list[Component]
    sheets: list[str] = Field(default_factory=lambda: ["/"])
    nets: dict[str, list[str]] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list)
    files: list[SourceFile] = Field(default_factory=list)
    parser_version: str = "0.0.0"

    def bom_components(self) -> list[Component]:
        """Components that belong in a BOM (``in_bom`` and not power/virtual symbols)."""
        return [c for c in self.components if c.in_bom and not c.refdes.startswith("#")]


class AppliedPart(StrEnum):
    NONE = "none"
    B = "B"
    BF = "BF"
    CF = "CF"


class PowerSource(StrEnum):
    MAINS = "mains"
    BATTERY = "battery"
    USB = "usb"
    EXTERNAL_PSU = "external_psu"


class Requirements(_Model):
    """Device requirements entered in the "Nowy przebieg" modal."""

    device_name: str = ""
    applied_part: AppliedPart = AppliedPart.NONE
    defibrillation_proof: bool = False
    power_source: PowerSource = PowerSource.BATTERY
    notes: str = Field(default="", max_length=4000)
    preferred_manufacturers: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- provenance
class KbCitation(_Model):
    document_id: str
    chunk_id: str
    page: int | None = None
    scope: Literal["global", "tenant"] = "global"
    quote: str = Field(default="", max_length=500)


class ProvenanceKind(StrEnum):
    PARSER = "parser"
    RULE = "rule"
    AGENT = "agent"
    USER = "user"


class Provenance(_Model):
    kind: ProvenanceKind
    # rule decisions
    rule_id: str | None = None
    rule_pack: str | None = None
    rule_pack_version: str | None = None
    # agent decisions
    agent: str | None = None
    model_id: str | None = None
    prompt_id: str | None = None
    prompt_version: str | None = None
    citations: list[KbCitation] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=2000)
    # parser / user
    parser: str | None = None
    user_id: str | None = None
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_parser(cls, parser: str) -> Provenance:
        return cls(kind=ProvenanceKind.PARSER, parser=parser)

    @classmethod
    def from_rule(cls, rule_id: str, pack: str, version: str, rationale: str = "") -> Provenance:
        return cls(
            kind=ProvenanceKind.RULE,
            rule_id=rule_id,
            rule_pack=pack,
            rule_pack_version=version,
            rationale=rationale,
        )


# --------------------------------------------------------------------------- output side
class BomItem(_Model):
    """One BOM line (grouped identical parts)."""

    line: int = Field(ge=1)
    refdes: list[RefDes] = Field(min_length=1)
    quantity: int = Field(ge=1)
    kind: str = "other"
    value: str = ""
    value_normalized: str | None = None
    footprint: str = ""
    package: str | None = None
    manufacturer: str = ""
    mpn: str = ""
    description: str = ""
    dnp: bool = False
    fields: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, Provenance] = Field(
        default_factory=dict,
        description="Who decided each field: keys are field names or 'item' for the line.",
    )

    @field_validator("refdes")
    @classmethod
    def _sorted_unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate reference designators in one line")
        return sort_refdes(v)


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    REVIEW = "review"  # checklist flag for a human reviewer (e.g. IEC 60601)
    INFO = "info"


class Finding(_Model):
    rule_id: str
    severity: Severity
    message: str
    refdes: list[str] = Field(default_factory=list)
    field: str | None = None
    line: int | None = None
    rule_pack: str = ""
    rule_pack_version: str = ""


class Usage(_Model):
    """Cost accounting of producing a BOM (thesis metric PB3)."""

    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cost_eur: float = 0.0
    wall_time_s: float = 0.0
    tool_calls: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            llm_calls=self.llm_calls + other.llm_calls,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            cost_eur=round(self.cost_eur + other.cost_eur, 6),
            wall_time_s=self.wall_time_s + other.wall_time_s,
            tool_calls=self.tool_calls + other.tool_calls,
        )


class BomVersion(_Model):
    schema_version: str = SCHEMA_VERSION
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    design_name: str
    variant: str = ""
    items: list[BomItem]
    findings: list[Finding] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    kb_snapshot_id: str | None = None
    rule_pack: str | None = None
    rule_pack_version: str | None = None

    def refdes_index(self) -> dict[str, BomItem]:
        return {r: item for item in self.items for r in item.refdes}

    @property
    def total_parts(self) -> int:
        return sum(i.quantity for i in self.items if not i.dnp)
