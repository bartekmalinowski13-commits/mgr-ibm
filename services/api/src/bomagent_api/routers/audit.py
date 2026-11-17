"""Audit log of the organisation (filterable, cursor-paginated) and chain verification."""

from __future__ import annotations

from fastapi import APIRouter, Request

from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.schemas import AuditEventOut, ChainStatus, Page, problem_responses
from bomagent_api.services import audit as service

router = APIRouter(
    prefix="/v1/audit-events",
    tags=["audit"],
    responses=problem_responses(400, 401, 403, 404, 409, 413, 422, 429),
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
    return await service.list_events(
        request.app.state.engine,
        cursor=cursor,
        limit=limit,
        object_type=object_type,
        actor_id=actor_id,
    )


@router.get("/verify", summary="Verify the organisation's audit hash chain")
async def verify(request: Request, ctx: OrgContext) -> ChainStatus:
    require(ctx, "audit.read")
    sink = getattr(request.app.state, "anchor_sink", None)
    return await service.verify(request.app.state.engine, sink, ctx.tenant_id)
