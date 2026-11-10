"""Audit log of the organisation (filterable, cursor-paginated) and chain verification."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text

from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.pagination import clamp
from bomagent_api.schemas import AuditEventOut, ChainStatus, Page, problem_responses
from bomagent_common.audit import verify_chain
from bomagent_common.db import tenant_transaction

router = APIRouter(
    prefix="/v1/audit-events",
    tags=["audit"],
    responses=problem_responses(400, 401, 403, 404, 409, 413, 422),
)


@router.get("", summary="Audit events (newest first)")
async def list_events(
    request: Request,
    ctx: OrgContext,
    cursor: str | None = None,
    limit: int = 50,
    object_type: str | None = None,
    actor_id: str | None = None,
) -> Page[AuditEventOut]:
    require(ctx, "audit.read")
    params: dict[str, Any] = {"lim": clamp(limit) + 1}
    where = ""
    if cursor:
        where += " AND seq < :c"
        params["c"] = int(cursor) if cursor.isdigit() else 0
    if object_type:
        where += " AND object_type = :ot"
        params["ot"] = object_type
    if actor_id:
        where += " AND actor_id = :a"
        params["a"] = actor_id
    cols = "seq, occurred_at, actor_type, actor_id, action, object_type, object_id, before, after"
    # ``where`` is built from constant clauses only; values are bound parameters
    sql = f"SELECT {cols} FROM audit.events WHERE true{where} ORDER BY seq DESC LIMIT :lim"  # noqa: S608
    async with tenant_transaction(request.app.state.engine) as conn:
        rows = [dict(r._mapping) for r in await conn.execute(text(sql), params)]
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    return Page[AuditEventOut](
        items=[AuditEventOut(**r) for r in rows], next_cursor=str(rows[-1]["seq"]) if more else None
    )


@router.get("/verify", summary="Verify the organisation's audit hash chain")
async def verify(request: Request, ctx: OrgContext) -> ChainStatus:
    require(ctx, "audit.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        result = await verify_chain(conn, ctx.tenant_id)
    return ChainStatus(
        ok=result.ok, checked=result.checked, first_broken_seq=result.first_broken_seq
    )
