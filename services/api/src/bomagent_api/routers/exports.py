"""Export of the organisation's data (GDPR Art. 15/20, audit SEC-14).

``POST /v1/organizations/{id}/export`` starts an asynchronous job (outbox -> ``kb`` queue ->
``bomagent_kb_indexer.export``); the ZIP lands under the tenant prefix of the object store
and is fetched through a short-lived signed link. Owners and admins only, signed-in users
only (not API keys), at most ``MAX_EXPORTS_PER_DAY`` per organisation and 24 hours; every
step is audited. The path id must be the active organisation: any other id answers 404.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request

from bomagent_api import idempotency
from bomagent_api.auth import OrgContext
from bomagent_api.schemas import ExportDownload, ExportJob, problem_responses
from bomagent_api.services import exports as service

router = APIRouter(
    prefix="/v1/organizations/{org_id}/export",
    tags=["organization"],
    responses=problem_responses(400, 401, 403, 404, 409, 410, 422, 429),
)


@router.post("", status_code=202, summary="Start an export of the organisation's data (ZIP)")
async def start_export(
    request: Request,
    ctx: OrgContext,
    org_id: uuid.UUID,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> ExportJob:
    """Projects (with file metadata), runs, every BOM version (JSON + CSV), the
    organisation's knowledge-base documents (metadata) and the audit log. Poll
    ``GET .../export/{job_id}``, then fetch ``.../download``."""
    service.authorize(ctx, org_id)
    state = request.app.state
    return await service.start_export(
        ctx,
        org_id,
        engine=state.engine,
        store=state.store,
        queues=state.queues,
        idempotency_key=idempotency_key,
        route=idempotency.route_of(request),
    )


@router.get("/{job_id}", summary="State of an export")
async def get_export(
    request: Request, ctx: OrgContext, org_id: uuid.UUID, job_id: uuid.UUID
) -> ExportJob:
    service.authorize(ctx, org_id)
    return await service.get_export(ctx, job_id, store=request.app.state.store)


@router.get("/{job_id}/download", summary="Short-lived download link of a finished export")
async def download_export(
    request: Request, ctx: OrgContext, org_id: uuid.UUID, job_id: uuid.UUID
) -> ExportDownload:
    service.authorize(ctx, org_id)
    state = request.app.state
    return await service.download_export(ctx, job_id, engine=state.engine, store=state.store)
