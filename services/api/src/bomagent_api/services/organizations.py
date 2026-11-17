"""Organisation onboarding, usage report and sample seeding (ARCH-04)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_api.plans import hit_rate_limit, plan_of, usage_report
from bomagent_api.repositories import organizations as repo
from bomagent_api.samples.seeding import SeedResult, seed_samples
from bomagent_api.schemas import Organization, OrganizationCreate, SamplesAdded, UsageReport
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import platform_transaction, tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext

log = get_logger(__name__)
_BACKGROUND: set[asyncio.Task[Any]] = set()  # keeps shielded seeding tasks alive


async def create_organization(
    *,
    platform_engine: AsyncEngine,
    engine: AsyncEngine,
    store: Any,
    queues: Any,
    samples_enabled: bool,
    sub: str,
    email: str,
    name: str,
    body: OrganizationCreate,
) -> Organization:
    """The caller becomes the owner. Tenant creation runs with the platform role (the
    application role cannot create tenants); the audit event lands in the new tenant in
    the same transaction."""
    org_id = uuid.uuid4()
    ctx = TenantContext(tenant_id=org_id, actor_id=sub, roles=frozenset({"owner"}))
    try:
        async with platform_transaction(platform_engine) as conn:
            await repo.create_with_owner(
                conn,
                org_id=org_id,
                slug=body.slug,
                name=body.name,
                owner_sub=sub,
                owner_email=email,
                owner_name=name,
            )
            await emit_audit(
                conn,
                AuditEvent(
                    action="org.created",
                    object_type="organization",
                    object_id=str(org_id),
                    after={"slug": body.slug, "name": body.name},
                ),
                ctx,
            )
    except IntegrityError as exc:
        raise ProblemError(
            409, "Conflict", "organisation slug already taken", slug="slug-taken"
        ) from exc
    if samples_enabled:
        # best effort: organisation creation never fails because of the samples, and a
        # client disconnect does not cancel a half-done seeding (POST /v1/samples fills gaps)
        task = asyncio.create_task(
            seed_samples(ctx, engine=engine, store=store, queues=queues, trigger="org_created")
        )
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)
        try:
            await asyncio.shield(task)
        except Exception:
            log.exception("samples_seed_failed", tenant_id=str(org_id))
    return Organization(id=org_id, slug=body.slug, name=body.name, plan="pilot")


async def usage(engine: AsyncEngine) -> UsageReport:
    async with tenant_transaction(engine) as conn:
        return UsageReport(**await usage_report(conn))


async def add_samples(
    ctx: TenantContext,
    *,
    engine: AsyncEngine,
    store: Any,
    queues: Any,
    samples_enabled: bool,
) -> SamplesAdded:
    """Adds every sample project that is missing (idempotent: nothing is added twice)."""
    async with tenant_transaction(engine, ctx.tenant_id) as conn:
        plan = await plan_of(conn)
        # each call may write files: a small extra limit on top of the per-user one
        await hit_rate_limit(conn, f"samples:{ctx.actor_id}", replace(plan, requests_per_minute=5))
    if not samples_enabled:
        raise ProblemError(
            404, "Not Found", "sample projects are disabled on this deployment", slug="not-found"
        )
    result: SeedResult = await seed_samples(
        ctx, engine=engine, store=store, queues=queues, trigger="manual"
    )
    return SamplesAdded(added=result.added, existing=result.existing)
