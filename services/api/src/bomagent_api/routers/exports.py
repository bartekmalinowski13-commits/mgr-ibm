"""Export of the organisation's data (GDPR Art. 15/20, audit SEC-14).

``POST /v1/organizations/{id}/export`` starts an asynchronous job (outbox -> ``kb`` queue ->
``bomagent_kb_indexer.export``); the ZIP lands under the tenant prefix of the object store
and is fetched through a short-lived signed link. Owners and admins only, signed-in users
only (not API keys), at most ``MAX_EXPORTS_PER_DAY`` per organisation and 24 hours; every
step is audited. The path id must be the active organisation: any other id answers 404.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from sqlalchemy import text

from bomagent_api import idempotency
from bomagent_api.auth import OrgContext
from bomagent_api.authz import ADMIN
from bomagent_api.plans import quota_exceeded
from bomagent_api.routers.projects import deliver_now
from bomagent_api.schemas import ExportDownload, ExportJob, problem_responses
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import Message
from bomagent_common.org_export import (
    DOWNLOAD_LINK_TTL_S,
    EXPORT_REQUESTED,
    MAX_EXPORTS_PER_DAY,
    ExportStatus,
    archive_key,
    read_status,
    write_status,
)
from bomagent_common.outbox import enqueue
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext

router = APIRouter(
    prefix="/v1/organizations/{org_id}/export",
    tags=["organization"],
    responses=problem_responses(400, 401, 403, 404, 409, 410, 422, 429),
)


def _authorize(ctx: TenantContext, org_id: uuid.UUID) -> None:
    if org_id != ctx.tenant_id:  # same answer as for an organisation that does not exist
        raise ProblemError(404, "Not Found", "organisation not found", slug="not-found")
    if ctx.actor_type != "user" or not ctx.roles & ADMIN:
        raise ProblemError(
            403,
            "Forbidden",
            "only an owner or admin can export the organisation's data",
            slug="forbidden-action",
        )


async def _job(request: Request, ctx: TenantContext, job_id: uuid.UUID) -> ExportStatus:
    status = await read_status(request.app.state.store, ctx.tenant_id, job_id)
    if status is None:
        raise ProblemError(404, "Not Found", "export not found", slug="not-found")
    return status


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
    _authorize(ctx, org_id)
    body: dict[str, Any] = {"org_id": str(org_id)}
    route = idempotency.route_of(request)
    async with tenant_transaction(request.app.state.engine) as conn:
        stored = await idempotency.replay(conn, idempotency_key, body, route=route)
        if stored is not None:
            return ExportJob(**stored)
        recent = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM audit.events WHERE action = :a"
                    " AND occurred_at > now() - interval '24 hours'"
                ),
                {"a": EXPORT_REQUESTED},
            )
        ).scalar() or 0
        if recent >= MAX_EXPORTS_PER_DAY:
            raise quota_exceeded(f"at most {MAX_EXPORTS_PER_DAY} exports per 24 hours")
        status = ExportStatus(
            id=uuid.uuid4(),
            status="queued",
            requested_by=ctx.actor_id,
            requested_at=datetime.now(UTC),
        )
        # before the commit: the worker never sees a message without a job
        await write_status(request.app.state.store, ctx.tenant_id, status)
        await emit_audit(
            conn,
            AuditEvent(
                action=EXPORT_REQUESTED,
                object_type="organization_export",
                object_id=str(status.id),
            ),
        )
        outbox_id = await enqueue(
            conn, "kb", Message.create(EXPORT_REQUESTED, ctx, {"job_id": str(status.id)})
        )
        job = ExportJob(**status.model_dump())
        await idempotency.store(
            conn, idempotency_key, body, 202, job.model_dump(mode="json"), route=route
        )
    await deliver_now(request, ctx.tenant_id, outbox_id)
    return job


@router.get("/{job_id}", summary="State of an export")
async def get_export(
    request: Request, ctx: OrgContext, org_id: uuid.UUID, job_id: uuid.UUID
) -> ExportJob:
    _authorize(ctx, org_id)
    return ExportJob(**(await _job(request, ctx, job_id)).model_dump())


@router.get("/{job_id}/download", summary="Short-lived download link of a finished export")
async def download_export(
    request: Request, ctx: OrgContext, org_id: uuid.UUID, job_id: uuid.UUID
) -> ExportDownload:
    _authorize(ctx, org_id)
    status = await _job(request, ctx, job_id)
    if status.status != "completed":
        raise ProblemError(
            409, "Conflict", f"the export is {status.status}", slug="export-not-ready"
        )
    if status.expires_at is not None and status.expires_at <= datetime.now(UTC):
        raise ProblemError(410, "Gone", "the export has expired; start a new one", slug="expired")
    url = await request.app.state.store.presign_get(
        archive_key(ctx.tenant_id, job_id), DOWNLOAD_LINK_TTL_S
    )
    async with tenant_transaction(request.app.state.engine) as conn:
        await emit_audit(
            conn,
            AuditEvent(
                action="org.export.downloaded",
                object_type="organization_export",
                object_id=str(job_id),
            ),
        )
    return ExportDownload(url=url, expires_in_s=DOWNLOAD_LINK_TTL_S)
