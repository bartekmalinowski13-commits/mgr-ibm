"""Export of the organisation's data (GDPR Art. 15/20, audit SEC-14); see the router for
the contract. Owners and admins only, signed-in users only (not API keys), at most
``MAX_EXPORTS_PER_DAY`` per organisation and 24 hours; every step is audited."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_api import idempotency
from bomagent_api.authz import ADMIN
from bomagent_api.plans import plan_of, quota_exceeded
from bomagent_api.repositories import audit as audit_repo
from bomagent_api.schemas import ExportDownload, ExportJob
from bomagent_api.services.outbox import deliver_now
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


def authorize(ctx: TenantContext, org_id: uuid.UUID) -> None:
    if org_id != ctx.tenant_id:  # same answer as for an organisation that does not exist
        raise ProblemError(404, "Not Found", "organisation not found", slug="not-found")
    if ctx.actor_type != "user" or not ctx.roles & ADMIN:
        raise ProblemError(
            403,
            "Forbidden",
            "only an owner or admin can export the organisation's data",
            slug="forbidden-action",
        )


async def _job(store: Any, ctx: TenantContext, job_id: uuid.UUID) -> ExportStatus:
    status = await read_status(store, ctx.tenant_id, job_id)
    if status is None:
        raise ProblemError(404, "Not Found", "export not found", slug="not-found")
    return status


async def start_export(
    ctx: TenantContext,
    org_id: uuid.UUID,
    *,
    engine: AsyncEngine,
    store: Any,
    queues: Any,
    idempotency_key: str | None,
    route: str,
) -> ExportJob:
    body: dict[str, Any] = {"org_id": str(org_id)}
    async with tenant_transaction(engine) as conn:
        stored = await idempotency.replay(conn, idempotency_key, body, route=route)
        if stored is not None:
            return ExportJob(**stored)
        await plan_of(conn, lock=True)  # serialises the daily cap of concurrent requests
        recent = await audit_repo.count_events_last_24h(conn, EXPORT_REQUESTED)
        if recent >= MAX_EXPORTS_PER_DAY:
            raise quota_exceeded(f"at most {MAX_EXPORTS_PER_DAY} exports per 24 hours")
        status = ExportStatus(
            id=uuid.uuid4(),
            status="queued",
            requested_by=ctx.actor_id,
            requested_at=datetime.now(UTC),
        )
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
        # the last step before the commit: the worker never sees a message without a job,
        # and a transaction that failed earlier leaves no job that stays "queued" for ever
        await write_status(store, ctx.tenant_id, status)
    await deliver_now(engine, queues, ctx.tenant_id, outbox_id)
    return job


async def get_export(ctx: TenantContext, job_id: uuid.UUID, *, store: Any) -> ExportJob:
    return ExportJob(**(await _job(store, ctx, job_id)).model_dump())


async def download_export(
    ctx: TenantContext, job_id: uuid.UUID, *, engine: AsyncEngine, store: Any
) -> ExportDownload:
    status = await _job(store, ctx, job_id)
    if status.status != "completed":
        raise ProblemError(
            409, "Conflict", f"the export is {status.status}", slug="export-not-ready"
        )
    if status.expires_at is not None and status.expires_at <= datetime.now(UTC):
        raise ProblemError(410, "Gone", "the export has expired; start a new one", slug="expired")
    url = await store.presign_get(archive_key(ctx.tenant_id, job_id), DOWNLOAD_LINK_TTL_S)
    async with tenant_transaction(engine) as conn:
        await emit_audit(
            conn,
            AuditEvent(
                action="org.export.downloaded",
                object_type="organization_export",
                object_id=str(job_id),
            ),
        )
    return ExportDownload(url=url, expires_in_s=DOWNLOAD_LINK_TTL_S)
