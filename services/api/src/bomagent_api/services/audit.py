"""Audit log of the organisation (filterable, cursor-paginated) and chain verification."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_api.pagination import clamp, decode_seq_cursor, encode_seq_cursor
from bomagent_api.repositories import audit as repo
from bomagent_api.schemas import AuditEventOut, ChainStatus, Page
from bomagent_common.audit import ChainAnchor, verify_chain
from bomagent_common.audit_anchor import load_anchors
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger

log = get_logger(__name__)


async def list_events(
    engine: AsyncEngine,
    *,
    cursor: str | None,
    limit: int,
    object_type: str | None,
    actor_id: str | None,
) -> Page[AuditEventOut]:
    async with tenant_transaction(engine) as conn:
        rows = await repo.list_events(
            conn,
            before_seq=decode_seq_cursor(cursor),
            limit=clamp(limit) + 1,
            object_type=object_type,
            actor_id=actor_id,
        )
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    return Page[AuditEventOut](
        items=[AuditEventOut(**r) for r in rows],
        next_cursor=encode_seq_cursor(rows[-1]["seq"]) if more else None,
    )


async def recent_count(conn: Any, action: str) -> int:
    """Events of an action in the last 24 hours (used for per-day quotas)."""
    return await repo.count_events_last_24h(conn, action)


async def verify(engine: AsyncEngine, anchor_sink: Any, tenant_id: uuid.UUID) -> ChainStatus:
    anchors: list[ChainAnchor] | None = None
    anchors_error = False
    if anchor_sink is not None:
        try:
            anchors = await load_anchors(anchor_sink, tenant_id)
        except Exception:
            # the chain is still checked; the answer says that the anchors could not be
            log.exception("audit_anchors_unavailable", tenant_id=str(tenant_id))
            anchors_error = True
    async with tenant_transaction(engine) as conn:
        result = await verify_chain(conn, tenant_id, anchors)
    return ChainStatus(
        ok=result.ok,
        checked=result.checked,
        first_broken_seq=result.first_broken_seq,
        anchors_checked=len(anchors or []),
        anchors_error=anchors_error,
    )
