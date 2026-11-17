"""Who am I, onboarding of organisations, local mock IdP."""

from __future__ import annotations

from fastapi import APIRouter, Request

from bomagent_api.auth import CurrentPrincipal, OrgContext, memberships, require_verified_email
from bomagent_api.authz import require
from bomagent_api.plans import MAX_OWNED_ORGANIZATIONS, quota_exceeded
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
from bomagent_api.services import organizations as service
from bomagent_common.problems import ProblemError

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
    state = request.app.state
    return await service.create_organization(
        platform_engine=state.platform_engine,
        engine=state.engine,
        store=state.store,
        queues=state.queues,
        samples_enabled=state.samples_enabled,
        sub=principal.sub,
        email=principal.email,
        name=principal.name,
        body=body,
    )


@router.get("/usage", summary="Usage this month and the plan's limits")
async def usage(request: Request, ctx: OrgContext) -> UsageReport:
    require(ctx, "usage.read")
    return await service.usage(request.app.state.engine)


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
