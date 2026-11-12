"""Who am I, onboarding of organisations, local mock IdP."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from bomagent_api.auth import CurrentPrincipal, OrgContext, memberships, require_verified_email
from bomagent_api.authz import require
from bomagent_api.plans import MAX_OWNED_ORGANIZATIONS, quota_exceeded, usage_report
from bomagent_api.schemas import (
    DevToken,
    Me,
    Membership,
    Organization,
    OrganizationCreate,
    Token,
    UsageReport,
    problem_responses,
)
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import platform_transaction, tenant_transaction
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext

router = APIRouter(
    prefix="/v1",
    tags=["identity"],
    responses=problem_responses(400, 401, 403, 404, 409, 413, 422, 429),
)


@router.get("/me", summary="Current user and organisations")
async def me(request: Request, principal: CurrentPrincipal) -> Me:
    orgs = await memberships(request, principal)
    return Me(
        sub=principal.sub,
        email=principal.email,
        name=principal.name,
        organizations=[
            Membership(
                org_id=m["tenant_id"], slug=m["slug"], name=m["name"], roles=list(m["roles"])
            )
            for m in orgs
            if m["status"] == "active"
        ],
    )


@router.post("/organizations", status_code=201, summary="Create an organisation (onboarding)")
async def create_organization(
    request: Request, principal: CurrentPrincipal, body: OrganizationCreate
) -> Organization:
    """The caller becomes the owner. Tenant creation runs with the platform role (the
    application role cannot create tenants); the audit event lands in the new tenant in
    the same transaction. A verified e-mail address is required."""
    await require_verified_email(request, principal)
    owned = [m for m in await memberships(request, principal) if "owner" in m["roles"]]
    if len(owned) >= MAX_OWNED_ORGANIZATIONS:
        raise quota_exceeded(f"a user can own at most {MAX_OWNED_ORGANIZATIONS} organisations")
    org_id = uuid.uuid4()
    ctx = TenantContext(tenant_id=org_id, actor_id=principal.sub, roles=frozenset({"owner"}))
    try:
        async with platform_transaction(request.app.state.platform_engine) as conn:
            await conn.execute(
                text("INSERT INTO tenancy.tenants (id, slug, name) VALUES (:i, :s, :n)"),
                {"i": org_id, "s": body.slug, "n": body.name},
            )
            await conn.execute(
                text(
                    "INSERT INTO tenancy.memberships (tenant_id, user_sub, email,"
                    " display_name, roles) VALUES (:t, :s, :e, :d,"
                    " ARRAY['owner'])"
                ),
                {
                    "t": org_id,
                    "s": principal.sub,
                    "e": principal.email.lower(),
                    "d": principal.name,
                },
            )
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org_id)}
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
    return Organization(id=org_id, slug=body.slug, name=body.name, plan="pilot")


@router.get("/usage", summary="Usage this month and the plan's limits")
async def usage(request: Request, ctx: OrgContext) -> UsageReport:
    require(ctx, "usage.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        return UsageReport(**await usage_report(conn))


@router.post(
    "/dev/token", summary="Local mock IdP (local/test environments only)", include_in_schema=False
)
async def dev_token(request: Request, body: DevToken) -> Token:
    idp = getattr(request.app.state, "local_idp", None)
    if idp is None:
        raise ProblemError(404, "Not Found")
    return Token(
        access_token=idp.issue(
            body.sub,
            body.email,
            body.name,
            email_verified=body.email_verified,
            identity_provider=body.identity_provider,
        )
    )
