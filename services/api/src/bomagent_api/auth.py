"""Authentication (ADR-0005): the API depends only on OIDC - a signed JWT from the IdP
(Amazon Cognito in AWS, any OIDC provider later). Locally and in tests a built-in mock
IdP signs tokens with an ephemeral key; it is refused in any other environment.

The active organisation comes from the ``X-Org-Id`` header and is checked against the
user's memberships in the database (roles come from the database, never from the
token), then becomes the request's ``TenantContext``.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, Header, Request
from jwt import PyJWKClient
from sqlalchemy import text

from bomagent_common.db import tenant_transaction, user_transaction
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext, tenant_scope

ALGORITHMS = ["RS256"]
API_KEY_PREFIX = "bomk_"
LOCAL_ISSUER = "https://local-idp.bomagent.invalid"


@dataclass(frozen=True)
class Principal:
    sub: str
    email: str
    name: str
    email_verified: bool = False


class TokenVerifier:
    """Validates signature, issuer, audience, expiry. ``jwks`` (dict) or ``jwks_url``."""

    def __init__(
        self, issuer: str, audience: str, *, jwks_url: str | None = None, public_key: Any = None
    ) -> None:
        self.issuer, self.audience = issuer, audience
        self._jwk_client = PyJWKClient(jwks_url, cache_keys=True) if jwks_url else None
        self._public_key = public_key

    def verify(self, token: str) -> Principal:
        try:
            key = (
                self._jwk_client.get_signing_key_from_jwt(token).key
                if self._jwk_client
                else self._public_key
            )
            claims = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "sub", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise ProblemError(
                401, "Unauthorized", "invalid or expired token", slug="invalid-token"
            ) from exc
        return Principal(
            sub=str(claims["sub"]),
            email=str(claims.get("email", "")),
            name=str(claims.get("name", "")),
            # OIDC: boolean; some IdPs (older Cognito) send the string "true"
            email_verified=claims.get("email_verified") in (True, "true"),
        )


class LocalIdp:
    """Mock identity provider for local development and tests only."""

    def __init__(self, audience: str) -> None:
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.verifier = TokenVerifier(LOCAL_ISSUER, audience, public_key=self._key.public_key())
        self.audience = audience

    def issue(
        self,
        sub: str,
        email: str,
        name: str = "",
        ttl_s: int = 3600,
        *,
        email_verified: bool = True,
    ) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "iss": LOCAL_ISSUER,
                "aud": self.audience,
                "sub": sub,
                "email": email,
                "name": name,
                "email_verified": email_verified,
                "iat": now,
                "exp": now + ttl_s,
            },
            self._key,
            algorithm="RS256",
        )


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ProblemError(401, "Unauthorized", "missing bearer token", slug="missing-token")
    return authorization.split(" ", 1)[1].strip()


async def current_principal(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> Principal:
    token = _bearer(authorization)
    if token.startswith(API_KEY_PREFIX):
        raise ProblemError(
            401, "Unauthorized", "this endpoint needs a user token", slug="user-token-required"
        )
    return await _verify_user(request, token)


async def _verify_user(request: Request, token: str) -> Principal:
    verifier: TokenVerifier = request.app.state.verifier
    if verifier._jwk_client is None:
        return verifier.verify(token)
    return await asyncio.to_thread(verifier.verify, token)  # JWKS fetch blocks


async def memberships(request: Request, principal: Principal) -> list[dict[str, Any]]:
    async with user_transaction(request.app.state.engine, principal.sub) as conn:
        rows = await conn.execute(
            text("SELECT tenant_id, slug, name, roles, status FROM tenancy.memberships_of(:sub)"),
            {"sub": principal.sub},
        )
        return [dict(r._mapping) for r in rows]


def api_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def api_key_context(request: Request, key: str) -> TenantContext:
    """Resolve an organisation API key. The lookup runs without tenant context; RLS
    (``api_key_lookup``) shows only the active key with this exact hash."""
    engine = request.app.state.engine
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.api_key_hash', :h, true)"), {"h": api_key_hash(key)}
        )
        row = (
            await conn.execute(text("SELECT id, tenant_id, roles FROM tenancy.api_keys"))
        ).first()
    if row is None:
        raise ProblemError(401, "Unauthorized", "invalid or expired token", slug="invalid-token")
    async with tenant_transaction(engine, row.tenant_id) as conn:
        await conn.execute(
            text(
                "UPDATE tenancy.api_keys SET last_used_at = now() WHERE id = :i AND"
                " (last_used_at IS NULL OR last_used_at < now() - interval '1 minute')"
            ),
            {"i": row.id},
        )
    return TenantContext(
        tenant_id=row.tenant_id,
        actor_id=f"apikey:{row.id}",
        actor_type="api_key",
        roles=frozenset(row.roles),
        request_id=request.headers.get("x-request-id"),
    )


async def still_authorized(request: Request, ctx: TenantContext) -> bool:
    """Re-check for long-lived responses (SSE): membership or key still active."""
    if ctx.actor_type == "api_key":
        engine = request.app.state.engine
        async with tenant_transaction(engine, ctx.tenant_id) as conn:
            active = await conn.execute(
                text(
                    "SELECT 1 FROM tenancy.api_keys WHERE id = :i AND revoked_at IS NULL"
                    " AND (expires_at IS NULL OR expires_at > now())"
                ),
                {"i": uuid.UUID(ctx.actor_id.removeprefix("apikey:"))},
            )
            return active.first() is not None
    principal = Principal(sub=ctx.actor_id, email="", name="")
    return any(
        m["tenant_id"] == ctx.tenant_id and m["status"] == "active"
        for m in await memberships(request, principal)
    )


async def org_context(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_org_id: Annotated[str | None, Header()] = None,
) -> Any:
    """Dependency: the active organisation as TenantContext. A user token needs
    ``X-Org-Id`` and a membership (403 otherwise); an API key is bound to its own
    organisation (``X-Org-Id`` optional, must match)."""
    token = _bearer(authorization)
    if token.startswith(API_KEY_PREFIX):
        key_ctx = await api_key_context(request, token)
        if x_org_id and x_org_id != str(key_ctx.tenant_id):
            raise ProblemError(
                403, "Forbidden", "not a member of this organisation", slug="not-a-member"
            )
        with tenant_scope(key_ctx):
            yield key_ctx
        return
    principal = await _verify_user(request, token)
    if not x_org_id:
        raise ProblemError(400, "Bad Request", "header X-Org-Id is required", slug="org-required")
    try:
        org_id = uuid.UUID(x_org_id)
    except ValueError as exc:
        raise ProblemError(
            400, "Bad Request", "X-Org-Id must be a UUID", slug="org-required"
        ) from exc
    member = next(
        (
            m
            for m in await memberships(request, principal)
            if m["tenant_id"] == org_id and m["status"] == "active"
        ),
        None,
    )
    if member is None:
        # same answer whether the org exists or not: no enumeration of organisations
        raise ProblemError(
            403, "Forbidden", "not a member of this organisation", slug="not-a-member"
        )
    ctx = TenantContext(
        tenant_id=org_id,
        actor_id=principal.sub,
        actor_type="user",
        roles=frozenset(member["roles"]),
        request_id=request.headers.get("x-request-id"),
    )
    with tenant_scope(ctx):
        yield ctx


OrgContext = Annotated[TenantContext, Depends(org_context)]
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
