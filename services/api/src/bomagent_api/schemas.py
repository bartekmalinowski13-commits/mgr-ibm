"""Public API models (OpenAPI 3.1 contract, ADR-0015)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bomagent_bom.model import BomVersion, Requirements


def _no_nul(value: Any) -> Any:
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("NUL characters are not allowed")
    elif isinstance(value, dict):
        for v in value.values():
            _no_nul(v)
    elif isinstance(value, list):
        for v in value:
            _no_nul(v)
    return value


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def _reject_nul(cls, value: Any) -> Any:
        """PostgreSQL text cannot store NUL; reject it as a 422 instead of failing later."""
        return _no_nul(value)


class Membership(_M):
    org_id: uuid.UUID
    slug: str
    name: str
    roles: list[str]


class Me(_M):
    sub: str
    email: str
    name: str
    organizations: list[Membership]


class OrganizationCreate(_M):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")


class Organization(_M):
    id: uuid.UUID
    slug: str
    name: str
    plan: str


class ProjectCreate(_M):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)


class Project(_M):
    id: uuid.UUID
    name: str
    description: str
    created_by: str
    created_at: datetime


class FileInfo(_M):
    id: uuid.UUID
    name: str
    size_bytes: int
    sha256: str
    status: str
    detected_format: str | None
    summary: dict[str, Any]
    created_at: datetime


class RunCreate(_M):
    project_id: uuid.UUID
    variant: Literal["A", "B"]
    model_id: str = "fake-closed"
    runtime: Literal["langgraph_a", "langgraph_b", "claude_agent_sdk_a"] | None = None
    requirements: Requirements = Field(default_factory=Requirements)


class Run(_M):
    id: uuid.UUID
    project_id: uuid.UUID
    variant: str
    runtime: str
    model_id: str
    status: str
    usage: dict[str, Any]
    error: str | None
    created_by: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class BomEnvelope(_M):
    run_id: uuid.UUID
    version: int
    bom: BomVersion


class BomItemPatch(_M):
    mpn: str | None = Field(default=None, max_length=80)
    manufacturer: str | None = Field(default=None, max_length=120)
    value: str | None = Field(default=None, max_length=120)
    footprint: str | None = Field(default=None, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)


class AuditEventOut(_M):
    seq: int
    occurred_at: datetime
    actor_type: str
    actor_id: str
    action: str
    object_type: str
    object_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class ChainStatus(_M):
    ok: bool
    checked: int
    first_broken_seq: int | None


Role = Literal["owner", "admin", "engineer", "reviewer", "viewer"]


class Member(_M):
    user_sub: str
    email: str
    display_name: str
    roles: list[Role]
    created_at: datetime


class MemberUpdate(_M):
    roles: list[Role] = Field(min_length=1, max_length=5)


class InvitationCreate(_M):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    roles: list[Role] = Field(min_length=1, max_length=5)


class Invitation(_M):
    id: uuid.UUID
    email: str
    roles: list[Role]
    status: Literal["pending", "accepted", "revoked"]
    invited_by: str
    created_at: datetime
    expires_at: datetime


class InvitationCreated(Invitation):
    token: str = Field(description="Secret for the invitee; returned only once.")


class InvitationAccept(_M):
    token: str = Field(min_length=20, max_length=200)


class ModelOption(_M):
    id: str
    provider: str
    license_class: Literal["closed", "open-weight"]
    residency: str
    tier: str | None


class RunStep(_M):
    node: str
    duration_s: float
    llm_calls: int


class Counts(_M):
    tp: int
    fp: int
    fn: int


class FieldAccuracy(_M):
    correct: int
    compared: int
    reference_total: int


class ReferenceDiff(_M):
    refdes: str
    field: str
    predicted: str
    expected: str


class Evaluation(_M):
    run_id: uuid.UUID
    version: int
    reference_lines: int
    summary: dict[str, float | None] = Field(
        description="Thesis metrics (line P/R/F1, designator F1, MPN coverage, field accuracy,"
        " usage); null where a metric is undefined"
    )
    lines: Counts
    designators: Counts
    fields: dict[str, FieldAccuracy]
    diffs: list[ReferenceDiff]


class KbDocument(_M):
    id: uuid.UUID
    scope: Literal["global", "tenant"]
    title: str
    kind: str
    manufacturer: str
    status: Literal["pending", "indexing", "indexed", "failed"]
    error: str | None
    size_bytes: int
    chunks: int
    created_at: datetime
    indexed_at: datetime | None


class UsageReport(_M):
    plan: Literal["pilot", "team", "business", "enterprise"]
    usage: dict[str, float]
    limits: dict[str, float]


KeyRole = Literal["engineer", "reviewer", "viewer"]


class ApiKeyCreate(_M):
    name: str = Field(min_length=1, max_length=100)
    roles: list[KeyRole] = Field(min_length=1, max_length=3)
    expires_in_days: int | None = Field(default=None, ge=1, le=730)


class ApiKey(_M):
    id: uuid.UUID
    name: str
    prefix: str
    roles: list[KeyRole]
    created_by: str
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class ApiKeyCreated(ApiKey):
    key: str = Field(description="Secret API key; returned only once.")


class Page[T](_M):
    items: list[T]
    next_cursor: str | None


class DevToken(_M):
    sub: str = Field(min_length=1, max_length=255)
    email: str
    name: str = ""
    email_verified: bool = True


class Token(_M):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105 - token type, not a secret


def problem_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Declared RFC 9457 error responses for the OpenAPI contract."""
    from bomagent_common.problems import Problem

    return {
        code: {
            "model": Problem,
            "content": {"application/problem+json": {}},
            "description": "Problem details (RFC 9457)",
        }
        for code in codes
    }


COMMON_ERRORS = problem_responses(400, 401, 403, 404, 422)
