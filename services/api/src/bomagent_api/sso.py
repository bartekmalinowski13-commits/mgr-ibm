"""Single sign-on per organisation (ADR-0005): SAML 2.0 / OIDC federated in Cognito.

* **Domains** - an organisation proves it controls an e-mail domain with a DNS TXT record
  ``_bomagent-verify.<domain>`` = token; a verified domain belongs to one organisation.
* **Connection** - one identity provider per organisation, created in Cognito under a
  random provider name (stored with the connection). The OIDC client secret is passed to
  Cognito only, never stored by us.
* **Discovery** - the sign-in screen asks for the e-mail first; a verified domain with
  an active connection sends the user straight to their identity provider.
* **First sign-in** - a user who comes through the organisation's provider (Cognito's
  ``identities`` claim) with an e-mail in one of its verified domains becomes a member
  with the connection's default role (never owner/admin).
* **Enforcement** - with ``enforce`` on, members from the verified domains must sign in
  through the provider; owners are exempt (break-glass if the identity provider fails).

Lookups before any tenant context stay inside RLS (``app.sso_domain`` /
``app.sso_provider`` policies, migration 0010).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext

TXT_PREFIX = "_bomagent-verify"
SAML_EMAIL = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
SAML_NAME = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"


def new_provider_name() -> str:
    """Cognito identity provider name (<= 32 chars): random, so it reveals nothing about the
    organisation and cannot be guessed. Chosen once per connection and kept in
    ``tenancy.sso_connections.provider_name`` (connections created before keep their old name)."""
    return f"org-{secrets.token_hex(12)}"


#: public mailbox providers: nobody "owns" these domains, so they can never be claimed for SSO
#: (SEC-05). DNS ownership would fail anyway; this stops the attempt and the discovery oracle.
FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
        "yahoo.com", "ymail.com", "icloud.com", "me.com", "mac.com", "aol.com", "proton.me",
        "protonmail.com", "pm.me", "gmx.com", "gmx.net", "gmx.de", "web.de", "mail.com",
        "zoho.com", "yandex.com", "yandex.ru", "mail.ru", "wp.pl", "o2.pl", "onet.pl",
        "onet.eu", "interia.pl", "interia.eu", "poczta.fm", "op.pl", "tlen.pl", "gazeta.pl",
        "seznam.cz", "centrum.cz", "free.fr", "orange.fr", "laposte.net", "t-online.de",
        "libero.it", "tiscali.it", "qq.com", "163.com", "126.com",
    }
)  # fmt: skip


def is_free_mail(domain: str) -> bool:
    d = domain.strip().lower().rstrip(".")
    return d in FREE_MAIL_DOMAINS or any(d.endswith("." + f) for f in FREE_MAIL_DOMAINS)


def email_domain(email: str) -> str | None:
    _, at, domain = email.strip().lower().rpartition("@")
    return domain if at and "." in domain else None


def new_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Connection:
    protocol: Literal["saml", "oidc"]
    provider_name: str
    metadata_url: str | None = None
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None


# ------------------------------------------------------------------ identity providers
class IdentityProviders(Protocol):
    async def apply(self, connection: Connection, client_secret: str | None) -> None: ...

    async def remove(self, provider_name: str) -> None: ...


class InMemoryIdentityProviders:
    """Local/test stand-in for Cognito: remembers what would have been configured."""

    def __init__(self) -> None:
        self.providers: dict[str, Connection] = {}
        self.fail_with: str | None = None

    async def apply(self, connection: Connection, client_secret: str | None) -> None:
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        self.providers[connection.provider_name] = connection

    async def remove(self, provider_name: str) -> None:
        self.providers.pop(provider_name, None)


class CognitoIdentityProviders:
    """Federation in the Cognito user pool, enabled on the SPA app client."""

    def __init__(self, user_pool_id: str, client_id: str, region: str) -> None:
        import boto3

        self.pool, self.client_id = user_pool_id, client_id
        self._idp = boto3.client("cognito-idp", region_name=region)
        self._lock = asyncio.Lock()

    def _details(
        self, c: Connection, secret: str | None
    ) -> tuple[str, dict[str, str], dict[str, str]]:
        if c.protocol == "saml":
            return (
                "SAML",
                {"MetadataURL": c.metadata_url or "", "IDPSignout": "false"},
                {"email": SAML_EMAIL, "name": SAML_NAME},
            )
        details = {
            "client_id": c.oidc_client_id or "",
            "oidc_issuer": c.oidc_issuer or "",
            "authorize_scopes": "openid email profile",
            "attributes_request_method": "GET",
        }
        if secret:
            details["client_secret"] = secret
        return "OIDC", details, {"email": "email", "name": "name"}

    def _apply_sync(self, c: Connection, secret: str | None) -> None:
        kind, details, mapping = self._details(c, secret)
        try:
            self._idp.describe_identity_provider(UserPoolId=self.pool, ProviderName=c.provider_name)
            exists = True
        except self._idp.exceptions.ResourceNotFoundException:
            exists = False
        if exists:
            self._idp.update_identity_provider(
                UserPoolId=self.pool,
                ProviderName=c.provider_name,
                ProviderDetails=details,
                AttributeMapping=mapping,
            )
        else:
            self._idp.create_identity_provider(
                UserPoolId=self.pool,
                ProviderName=c.provider_name,
                ProviderType=kind,
                ProviderDetails=details,
                AttributeMapping=mapping,
            )
        self._set_client_providers(add=c.provider_name)

    def _set_client_providers(self, *, add: str | None = None, drop: str | None = None) -> None:
        client = self._idp.describe_user_pool_client(UserPoolId=self.pool, ClientId=self.client_id)[
            "UserPoolClient"
        ]
        providers = [p for p in client.get("SupportedIdentityProviders", []) if p != drop]
        if add and add not in providers:
            providers.append(add)
        # UpdateUserPoolClient resets omitted settings: send the current ones back
        keep = {
            k: v
            for k, v in client.items()
            if k
            not in {"ClientSecret", "CreationDate", "LastModifiedDate", "UserPoolId", "ClientId"}
        }
        keep["SupportedIdentityProviders"] = providers
        self._idp.update_user_pool_client(UserPoolId=self.pool, ClientId=self.client_id, **keep)

    def _remove_sync(self, provider_name: str) -> None:
        self._set_client_providers(drop=provider_name)
        with contextlib.suppress(self._idp.exceptions.ResourceNotFoundException):
            self._idp.delete_identity_provider(UserPoolId=self.pool, ProviderName=provider_name)

    async def apply(self, connection: Connection, client_secret: str | None) -> None:
        async with self._lock:  # one read-modify-write of the app client at a time
            await asyncio.to_thread(self._apply_sync, connection, client_secret)

    async def remove(self, provider_name: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._remove_sync, provider_name)


# The app client's provider list is read-modify-written; API replicas serialise on this
# Postgres advisory lock (an in-process lock alone loses updates across tasks).
PROVIDER_LOCK_KEY = 0x5B0_5503


@contextlib.asynccontextmanager
async def provider_change_lock(engine: AsyncEngine) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": PROVIDER_LOCK_KEY})
        yield


_INTERNAL_IDS = re.compile(
    r"arn:aws[a-z-]*:[^\s'\"]+"  # ARNs
    r"|\b[a-z]{2}-[a-z]+-\d_[A-Za-z0-9]+\b"  # Cognito user pool ids
    r"|\b\d{12}\b"  # AWS account ids
    r"|\b[0-9a-z]{26}\b"  # app client ids
)


def safe_error(exc: Exception, secret: str | None) -> str:
    """Broker failure for the admin: error code and message, never the client secret and
    never our own infrastructure identifiers (ARNs, account, pool and client ids)."""
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    message = f"{code or type(exc).__name__}: {exc}"
    if secret:
        message = message.replace(secret, "***")
    return _INTERNAL_IDS.sub("<redacted>", message)[:500]


# ------------------------------------------------------------------ DNS
class TxtResolver(Protocol):
    async def txt(self, name: str) -> list[str]: ...


class DnsTxtResolver:
    """TXT lookup over DNS (``dnspython``); failures count as "no record"."""

    async def txt(self, name: str) -> list[str]:
        import dns.asyncresolver
        import dns.exception

        try:
            answer = await dns.asyncresolver.resolve(name, "TXT", lifetime=5.0)
        except dns.exception.DNSException:
            return []
        return [b"".join(r.strings).decode("utf-8", "replace") for r in answer]


class StaticTxtResolver:
    """Local/test resolver: records set by the test (or by the local preview)."""

    def __init__(self) -> None:
        self.records: dict[str, list[str]] = {}

    async def txt(self, name: str) -> list[str]:
        return self.records.get(name.lower(), [])


# ------------------------------------------------------------------ lookups
async def discover(engine: AsyncEngine, domain: str) -> str | None:
    """Provider name for a verified domain with an active connection. Only the domain is
    asked for (never the e-mail address) and it is normalised here."""
    domain = domain.strip().lower().rstrip(".")
    if not domain or is_free_mail(domain):
        return None
    async with engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.sso_domain', :d, true)"), {"d": domain})
        row = (
            await conn.execute(text("SELECT provider_name FROM tenancy.sso_connections"))
        ).first()
    return str(row.provider_name) if row else None


async def join_on_first_sign_in(
    engine: AsyncEngine, sub: str, email: str, name: str, provider: str
) -> None:
    """Membership for a user who came through an organisation's identity provider."""
    domain = email_domain(email)
    if domain is None:
        return
    async with engine.begin() as conn:
        await conn.execute(text("SELECT set_config('app.sso_provider', :p, true)"), {"p": provider})
        conn_row = (
            await conn.execute(text("SELECT tenant_id, default_role FROM tenancy.sso_connections"))
        ).first()
    if conn_row is None:
        return
    async with tenant_transaction(engine, conn_row.tenant_id) as conn:
        verified = (
            await conn.execute(
                text(
                    "SELECT 1 FROM tenancy.sso_domains WHERE domain = :d"
                    " AND verified_at IS NOT NULL"
                ),
                {"d": domain},
            )
        ).first()
        if verified is None:
            return  # the provider may only vouch for its organisation's verified domains
        member = await conn.execute(
            text("SELECT 1 FROM tenancy.memberships WHERE user_sub = :s"), {"s": sub}
        )
        if member.first() is not None:
            return  # already a member: nothing to provision (the common case)
        removed = await conn.execute(
            text(
                "SELECT 1 FROM audit.events WHERE object_type = 'member' AND object_id = :s"
                " AND action = 'member.removed' LIMIT 1"
            ),
            {"s": sub},
        )
        if removed.first() is not None:
            # review I-1: an admin removed this user, and only a removal deletes a
            # membership; just-in-time provisioning must not undo it. An invitation brings
            # the user back (accepting it creates the membership, so this check is skipped).
            return
        inserted = (
            await conn.execute(
                text(
                    "INSERT INTO tenancy.memberships (tenant_id, user_sub, email, display_name,"
                    " roles) VALUES (app.current_tenant_id(), :s, :e, :n, ARRAY[:r])"
                    " ON CONFLICT (tenant_id, user_sub) DO NOTHING RETURNING user_sub"
                ),
                {"s": sub, "e": email.lower(), "n": name, "r": conn_row.default_role},
            )
        ).first()
        if inserted is not None:
            await emit_audit(
                conn,
                AuditEvent(
                    action="member.joined_via_sso",
                    object_type="member",
                    object_id=sub,
                    after={"email": email.lower(), "roles": [conn_row.default_role]},
                ),
                TenantContext(
                    tenant_id=conn_row.tenant_id,
                    actor_id=sub,
                    actor_type="user",
                    roles=frozenset({conn_row.default_role}),
                ),
            )


async def require_sso_if_enforced(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    sub: str,
    email: str,
    provider: str | None,
    roles: Any,
    *,
    auth_time: int | None = None,
    max_auth_age_s: int = 0,
) -> None:
    """403 ``sso-required`` for members from enforced domains signing in another way.

    A member who did sign in through the provider must have authenticated there within
    ``max_auth_age_s`` (token claim ``auth_time``; refresh tokens keep the original value):
    otherwise 401 ``reauth-required``, so a user removed at the customer's identity provider
    loses access within that window instead of at refresh-token expiry (SEC-05). ``0`` = off.

    The domain comes from the token **and** from the membership stored on our side: a
    member cannot step out of enforcement by changing the e-mail of their password
    account in Cognito (or by presenting a token without an e-mail).
    """
    if "owner" in roles:
        return  # break-glass: owners keep access if the identity provider fails
    async with tenant_transaction(engine, tenant_id) as conn:
        stored = await conn.scalar(
            text("SELECT email FROM tenancy.memberships WHERE user_sub = :s"), {"s": sub}
        )
        domains = sorted(
            {d for d in (email_domain(email or ""), email_domain(stored or "")) if d is not None}
        )
        if not domains:
            return
        row = (
            await conn.execute(
                text(
                    "SELECT c.provider_name FROM tenancy.sso_connections c"
                    " JOIN tenancy.sso_domains d ON d.tenant_id = c.tenant_id"
                    " WHERE c.enforce AND c.status = 'active' AND d.domain = ANY(:d)"
                    " AND d.verified_at IS NOT NULL"
                ),
                {"d": domains},
            )
        ).first()
    if row is None:
        return
    if provider != row.provider_name:
        raise ProblemError(
            403,
            "Forbidden",
            "this organisation requires single sign-on for your e-mail domain",
            slug="sso-required",
        )
    # fail closed: a token without ``auth_time`` cannot prove a recent sign-in
    if max_auth_age_s > 0 and (auth_time is None or time.time() - auth_time > max_auth_age_s):
        raise ProblemError(
            401,
            "Unauthorized",
            "sign in again through your identity provider",
            slug="reauth-required",
        )
