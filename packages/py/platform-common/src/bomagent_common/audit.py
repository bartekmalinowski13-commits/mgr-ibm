"""Audit event emitter (ADR-0011).

Every data-changing operation calls :func:`emit_audit` *inside the same transaction* as the
change, so the change and its audit record commit or roll back together. The hash chain
(``seq``, ``prev_hash``, ``hash``) is computed by a database trigger under a per-tenant
advisory lock - application code cannot forge or skip links. UPDATE/DELETE on
``audit.events`` are rejected by a trigger and revoked from application roles.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_common.tenancy import TenantContext, require_tenant


class AuditEvent(BaseModel):
    """What happened. Never put customer file contents here - identifiers and diffs only."""

    action: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    object_type: str
    object_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    source_ip: str | None = None


@dataclass(frozen=True, slots=True)
class AuditRecord:
    id: uuid.UUID
    seq: int
    hash: str
    prev_hash: str


@dataclass(frozen=True, slots=True)
class ChainVerification:
    ok: bool
    checked: int
    first_broken_seq: int | None


_INSERT = text(
    """
    INSERT INTO audit.events
        (id, tenant_id, actor_type, actor_id, action, object_type, object_id,
         source_ip, request_id, trace_id, before, after)
    VALUES
        (:id, :tenant_id, :actor_type, :actor_id, :action, :object_type, :object_id,
         CAST(:source_ip AS inet), :request_id, :trace_id,
         CAST(:before AS jsonb), CAST(:after AS jsonb))
    RETURNING seq, hash, prev_hash
    """
)


async def emit_audit(
    conn: AsyncConnection, event: AuditEvent, ctx: TenantContext | None = None
) -> AuditRecord:
    ctx = ctx or require_tenant()
    span_ctx = trace.get_current_span().get_span_context()
    event_id = uuid.uuid4()
    row = (
        await conn.execute(
            _INSERT,
            {
                "id": event_id,
                "tenant_id": ctx.tenant_id,
                "actor_type": ctx.actor_type,
                "actor_id": ctx.actor_id,
                "action": event.action,
                "object_type": event.object_type,
                "object_id": event.object_id,
                "source_ip": event.source_ip,
                "request_id": ctx.request_id,
                "trace_id": format(span_ctx.trace_id, "032x") if span_ctx.is_valid else None,
                "before": json.dumps(event.before) if event.before is not None else None,
                "after": json.dumps(event.after) if event.after is not None else None,
            },
        )
    ).one()
    return AuditRecord(id=event_id, seq=row.seq, hash=row.hash, prev_hash=row.prev_hash)


async def verify_chain(conn: AsyncConnection, tenant_id: uuid.UUID) -> ChainVerification:
    """Recompute the hash chain of one tenant (visible rows only - run in its context)."""
    row = (
        await conn.execute(
            text("SELECT checked, first_broken_seq FROM audit.verify_chain(:tid)"),
            {"tid": tenant_id},
        )
    ).one()
    return ChainVerification(
        ok=row.first_broken_seq is None, checked=row.checked, first_broken_seq=row.first_broken_seq
    )
