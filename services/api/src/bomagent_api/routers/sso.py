"""Single sign-on settings of the organisation (owner/admin) and sign-in discovery."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.schemas import (
    SsoConnection,
    SsoConnectionIn,
    SsoDiscovery,
    SsoDomain,
    SsoDomainIn,
    SsoSettings,
    problem_responses,
)
from bomagent_api.sso import (
    TXT_PREFIX,
    Connection,
    StaticTxtResolver,
    discover,
    new_token,
    provider_change_lock,
    provider_name_for,
    safe_error,
)
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.problems import ProblemError

router = APIRouter(
    prefix="/v1/sso", tags=["sso"], responses=problem_responses(400, 401, 403, 404, 409, 422, 429)
)
public = APIRouter(prefix="/v1/sso", tags=["sso"], responses=problem_responses(400, 422, 429))
COLS = (
    "protocol, provider_name, metadata_url, oidc_issuer, oidc_client_id, default_role,"
    " enforce, status, error"
)


def _sp(request: Request, protocol: str) -> dict[str, str | None]:
    """Values the customer registers at their identity provider (Cognito as SP)."""
    domain = (request.app.state.cognito_domain or "").removeprefix("https://").rstrip("/")
    pool = request.app.state.cognito_user_pool_id
    if not domain:
        return {"sp_acs_url": None, "sp_entity_id": None}
    path = "saml2/idpresponse" if protocol == "saml" else "oauth2/idpresponse"
    return {
        "sp_acs_url": f"https://{domain}/{path}",
        "sp_entity_id": f"urn:amazon:cognito:sp:{pool}" if pool else None,
    }


async def _settings(request: Request) -> SsoSettings:
    async with tenant_transaction(request.app.state.engine) as conn:
        row = (
            await conn.execute(text(f"SELECT {COLS} FROM tenancy.sso_connections"))  # noqa: S608
        ).first()
        domains = await conn.execute(
            text("SELECT domain, token, verified_at FROM tenancy.sso_domains ORDER BY domain")
        )
        domain_list = [
            SsoDomain(
                domain=d.domain,
                verified=d.verified_at is not None,
                txt_name=f"{TXT_PREFIX}.{d.domain}",
                txt_value=f"bomagent-verification={d.token}",
            )
            for d in domains
        ]
    connection = (
        SsoConnection.model_validate(dict(row._mapping) | _sp(request, row.protocol))
        if row is not None
        else None
    )
    return SsoSettings(connection=connection, domains=domain_list)


@router.get("", summary="Single sign-on settings of the organisation")
async def get_sso(request: Request, ctx: OrgContext) -> SsoSettings:
    require(ctx, "sso.manage")
    return await _settings(request)


@router.put("", summary="Create or change the organisation's identity provider")
async def put_sso(request: Request, ctx: OrgContext, body: SsoConnectionIn) -> SsoSettings:
    """Federates the identity provider in Cognito; ``status`` tells whether that worked.
    Enforcement needs an active connection and at least one verified domain."""
    require(ctx, "sso.manage")
    if body.protocol == "saml" and not body.metadata_url:
        raise ProblemError(422, "Unprocessable Content", "metadata_url is required for SAML")
    if body.protocol == "oidc" and not (body.oidc_issuer and body.oidc_client_id):
        raise ProblemError(
            422, "Unprocessable Content", "oidc_issuer and oidc_client_id are required for OIDC"
        )
    engine = request.app.state.engine
    name = provider_name_for(ctx.tenant_id)
    async with tenant_transaction(engine) as conn:
        before = (
            await conn.execute(text(f"SELECT {COLS} FROM tenancy.sso_connections"))  # noqa: S608
        ).first()
        verified = (
            await conn.execute(
                text("SELECT count(*) FROM tenancy.sso_domains WHERE verified_at IS NOT NULL")
            )
        ).scalar_one()
    if (
        body.protocol == "oidc"
        and not body.oidc_client_secret
        and (before is None or before.protocol != "oidc" or before.oidc_issuer != body.oidc_issuer)
    ):
        raise ProblemError(422, "Unprocessable Content", "oidc_client_secret is required")
    connection = Connection(
        protocol=body.protocol,
        provider_name=name,
        metadata_url=body.metadata_url if body.protocol == "saml" else None,
        oidc_issuer=body.oidc_issuer if body.protocol == "oidc" else None,
        oidc_client_id=body.oidc_client_id if body.protocol == "oidc" else None,
    )
    not_ready = ProblemError(
        409,
        "Conflict",
        "enforcement needs a working connection and at least one verified domain",
        slug="sso-not-ready",
    )
    if body.enforce and not verified:
        raise not_ready  # checked before Cognito is changed
    try:
        async with provider_change_lock(engine):
            await request.app.state.identity_providers.apply(connection, body.oidc_client_secret)
        status, error = "active", None
    except Exception as exc:  # the broker's message is shown to the admin, not raised
        status, error = "failed", safe_error(exc, body.oidc_client_secret)
    # whatever Cognito now holds is recorded and audited, even when the request is refused
    enforce = body.enforce and status == "active"
    async with tenant_transaction(engine) as conn:
        await conn.execute(
            text(
                "INSERT INTO tenancy.sso_connections (tenant_id, protocol, provider_name,"
                " metadata_url, oidc_issuer, oidc_client_id, default_role, enforce, status,"
                " error, created_by) VALUES (app.current_tenant_id(), :p, :n, :m, :i, :c, :r,"
                " :e, :s, :err, :u) ON CONFLICT (tenant_id) DO UPDATE SET protocol = :p,"
                " metadata_url = :m, oidc_issuer = :i, oidc_client_id = :c, default_role = :r,"
                " enforce = :e, status = :s, error = :err, updated_at = now()"
            ),
            {
                "p": connection.protocol,
                "n": name,
                "m": connection.metadata_url,
                "i": connection.oidc_issuer,
                "c": connection.oidc_client_id,
                "r": body.default_role,
                "e": enforce,
                "s": status,
                "err": error,
                "u": ctx.actor_id,
            },
        )
        await emit_audit(
            conn,
            AuditEvent(
                action="sso.updated",
                object_type="sso_connection",
                object_id=name,
                before=dict(before._mapping) if before is not None else None,
                after={
                    "protocol": connection.protocol,
                    "metadata_url": connection.metadata_url,
                    "oidc_issuer": connection.oidc_issuer,
                    "oidc_client_id": connection.oidc_client_id,
                    "default_role": body.default_role,
                    "enforce": enforce,
                    "status": status,
                },
            ),
        )
    if body.enforce and not enforce:
        raise not_ready
    return await _settings(request)


@router.delete("", status_code=204, summary="Remove the identity provider")
async def delete_sso(request: Request, ctx: OrgContext) -> Response:
    require(ctx, "sso.manage")
    name = provider_name_for(ctx.tenant_id)
    async with provider_change_lock(request.app.state.engine):
        await request.app.state.identity_providers.remove(name)
    async with tenant_transaction(request.app.state.engine) as conn:
        gone = await conn.execute(text("DELETE FROM tenancy.sso_connections RETURNING protocol"))
        if gone.first() is None:
            raise ProblemError(404, "Not Found", "no identity provider configured")
        await emit_audit(
            conn, AuditEvent(action="sso.deleted", object_type="sso_connection", object_id=name)
        )
    return Response(status_code=204)


@router.post("/domains", status_code=201, summary="Add an e-mail domain to verify")
async def add_domain(request: Request, ctx: OrgContext, body: SsoDomainIn) -> SsoDomain:
    """Idempotent: adding a domain again returns the same verification record."""
    require(ctx, "sso.manage")
    domain = body.domain.lower()
    async with tenant_transaction(request.app.state.engine) as conn:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO tenancy.sso_domains (tenant_id, domain, token)"
                    " VALUES (app.current_tenant_id(), :d, :t) ON CONFLICT (tenant_id, domain)"
                    " DO UPDATE SET domain = EXCLUDED.domain RETURNING token, verified_at,"
                    " (xmax = 0) AS created"
                ),
                {"d": domain, "t": new_token()},
            )
        ).one()
        if row.created:
            await emit_audit(
                conn,
                AuditEvent(action="sso.domain_added", object_type="sso_domain", object_id=domain),
            )
    return SsoDomain(
        domain=domain,
        verified=row.verified_at is not None,
        txt_name=f"{TXT_PREFIX}.{domain}",
        txt_value=f"bomagent-verification={row.token}",
    )


async def _domain(conn: Any, domain: str) -> Any:
    row = (
        await conn.execute(
            text("SELECT token, verified_at FROM tenancy.sso_domains WHERE domain = :d"),
            {"d": domain.lower()},
        )
    ).first()
    if row is None:
        raise ProblemError(404, "Not Found", "domain not found")
    return row


@router.post("/domains/{domain}/verify", summary="Check the domain's DNS TXT record")
async def verify_domain(request: Request, ctx: OrgContext, domain: str) -> SsoDomain:
    require(ctx, "sso.manage")
    domain = domain.lower()
    engine = request.app.state.engine
    async with tenant_transaction(engine) as conn:
        row = await _domain(conn, domain)
    expected = f"bomagent-verification={row.token}"
    if row.verified_at is None:
        records = await request.app.state.txt_resolver.txt(f"{TXT_PREFIX}.{domain}")
        if expected not in records:
            raise ProblemError(
                422,
                "Unprocessable Content",
                f"TXT record {TXT_PREFIX}.{domain} = {expected} not found (DNS may take time)",
                slug="domain-not-verified",
            )
        try:
            async with tenant_transaction(engine) as conn:
                await conn.execute(
                    text("UPDATE tenancy.sso_domains SET verified_at = now() WHERE domain = :d"),
                    {"d": domain},
                )
                await emit_audit(
                    conn,
                    AuditEvent(
                        action="sso.domain_verified", object_type="sso_domain", object_id=domain
                    ),
                )
        except IntegrityError as exc:
            raise ProblemError(
                409,
                "Conflict",
                "this domain is already verified by another organisation",
                slug="domain-taken",
            ) from exc
    return SsoDomain(
        domain=domain, verified=True, txt_name=f"{TXT_PREFIX}.{domain}", txt_value=expected
    )


@router.delete("/domains/{domain}", status_code=204, summary="Remove a domain")
async def delete_domain(request: Request, ctx: OrgContext, domain: str) -> Response:
    require(ctx, "sso.manage")
    async with tenant_transaction(request.app.state.engine) as conn:
        await _domain(conn, domain)
        await conn.execute(
            text("DELETE FROM tenancy.sso_domains WHERE domain = :d"), {"d": domain.lower()}
        )
        # enforcement without a verified domain would lock nobody out but mean nothing
        await conn.execute(
            text(
                "UPDATE tenancy.sso_connections SET enforce = false WHERE NOT EXISTS"
                " (SELECT 1 FROM tenancy.sso_domains WHERE verified_at IS NOT NULL)"
            )
        )
        await emit_audit(
            conn,
            AuditEvent(action="sso.domain_removed", object_type="sso_domain", object_id=domain),
        )
    return Response(status_code=204)


@public.get("/discover", summary="Identity provider for an e-mail address (sign-in)")
async def discover_sso(
    request: Request, email: str = Query(min_length=3, max_length=320)
) -> SsoDiscovery:
    """No authentication: the sign-in screen asks before any token exists. Reveals only
    whether a domain uses SSO and an opaque provider name."""
    provider = await discover(request.app.state.engine, email)
    return SsoDiscovery(sso=provider is not None, provider=provider)


@public.post(
    "/dev/dns", status_code=204, include_in_schema=False, summary="Local DNS (local/test only)"
)
async def dev_dns(request: Request, body: dict[str, str]) -> Response:
    """Local preview / E2E: set a TXT record the local resolver returns. Absent in the
    cloud (the real DNS resolver is used there)."""
    resolver = request.app.state.txt_resolver
    if getattr(request.app.state, "local_idp", None) is None or not isinstance(
        resolver, StaticTxtResolver
    ):
        raise ProblemError(404, "Not Found")
    resolver.records.setdefault(body.get("name", "").lower(), []).append(body.get("value", ""))
    return Response(status_code=204)
