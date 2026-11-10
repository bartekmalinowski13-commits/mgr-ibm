"""Authentication (OIDC bearer tokens) and role-based authorisation (ADR-0005).

The API depends only on OIDC: a JWT signed by the identity broker (Cognito in AWS; any
OIDC provider works) carrying the subject, the active organisation and the roles. A dev
authenticator with a shared HS256 secret exists for local development and tests and is
refused in staging/prod.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

import jwt

from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ENGINEER = "engineer"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


ALL_ROLES = frozenset(r.value for r in Role)
# what each operation needs (policy in code, Cedar-style: principal role -> action)
CAN_READ = (Role.OWNER, Role.ADMIN, Role.ENGINEER, Role.REVIEWER, Role.VIEWER)
CAN_WRITE = (Role.OWNER, Role.ADMIN, Role.ENGINEER)
CAN_AUDIT = (Role.OWNER, Role.ADMIN, Role.REVIEWER)


class Authenticator(Protocol):
    def authenticate(self, token: str) -> TenantContext: ...


def unauthorized(detail: str = "missing or invalid bearer token") -> ProblemError:
    return ProblemError(401, "Unauthorized", detail, slug="unauthorized")


def forbidden(detail: str = "your role does not allow this operation") -> ProblemError:
    return ProblemError(403, "Forbidden", detail, slug="forbidden")


def context_from_claims(
    claims: dict[str, Any], tenant_claim: str, roles_claim: str, request_id: str | None = None
) -> TenantContext:
    try:
        tenant_id = uuid.UUID(str(claims[tenant_claim]))
        subject = str(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise unauthorized("token has no valid organisation or subject") from exc
    raw_roles = claims.get(roles_claim) or []
    if isinstance(raw_roles, str):
        raw_roles = raw_roles.split()
    roles = frozenset(str(r) for r in raw_roles) & ALL_ROLES
    return TenantContext(
        tenant_id=tenant_id, actor_id=subject, actor_type="user", roles=roles, request_id=request_id
    )


@dataclass
class OidcAuthenticator:
    issuer: str
    audience: str
    jwks_url: str
    tenant_claim: str = "org_id"
    roles_claim: str = "roles"
    leeway: int = 30
    _jwks: Any = None

    def _key(self, token: str) -> Any:
        if self._jwks is None:
            self._jwks = jwt.PyJWKClient(self.jwks_url, cache_keys=True, lifespan=600)
        return self._jwks.get_signing_key_from_jwt(token).key

    def authenticate(self, token: str) -> TenantContext:
        try:
            claims = jwt.decode(
                token,
                self._key(token),
                algorithms=["RS256", "ES256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise unauthorized(f"token rejected: {type(exc).__name__}") from exc
        return context_from_claims(claims, self.tenant_claim, self.roles_claim)


@dataclass
class DevAuthenticator:
    """HS256 tokens signed with a local secret - local/test environments only."""

    secret: str
    audience: str = "bomagent-local"
    tenant_claim: str = "org_id"
    roles_claim: str = "roles"

    def authenticate(self, token: str) -> TenantContext:
        try:
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                audience=self.audience,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise unauthorized(f"token rejected: {type(exc).__name__}") from exc
        return context_from_claims(claims, self.tenant_claim, self.roles_claim)

    def issue(self, tenant_id: uuid.UUID, subject: str, roles: list[str], ttl: int = 3600) -> str:
        import time

        now = int(time.time())
        claims = {
            "sub": subject,
            "org_id": str(tenant_id),
            "roles": roles,
            "aud": self.audience,
            "iat": now,
            "exp": now + ttl,
        }
        return jwt.encode(claims, self.secret, algorithm="HS256")


def require(*roles: Role) -> Callable[[TenantContext], TenantContext]:
    allowed = {r.value for r in roles}

    def check(ctx: TenantContext) -> TenantContext:
        if not ctx.roles & allowed:
            raise forbidden()
        return ctx

    return check
