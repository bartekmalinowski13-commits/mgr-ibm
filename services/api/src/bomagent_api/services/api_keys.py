"""Organisation API keys for integrations (ARCHITECTURE §5): scoped roles, rotation,
only the SHA-256 of the secret in the database. Keys never get owner/admin roles."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bomagent_api.auth import API_KEY_PREFIX, api_key_hash
from bomagent_api.pagination import clamp, encode_cursor
from bomagent_api.repositories import api_keys as repo
from bomagent_api.schemas import ApiKey, ApiKeyCreate, ApiKeyCreated, Page
from bomagent_api.services.members import canonical
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext


async def _insert(
    conn: AsyncConnection,
    ctx: TenantContext,
    name: str,
    roles: list[str],
    expires_at: datetime | None,
) -> ApiKeyCreated:
    key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    row = await repo.insert_key(
        conn,
        name=name,
        prefix=key[:12],
        key_hash=api_key_hash(key),
        roles=roles,
        created_by=ctx.actor_id,
        expires_at=expires_at,
    )
    return ApiKeyCreated(**row, key=key)


async def _revoke(conn: AsyncConnection, key_id: uuid.UUID) -> Any:
    row = await repo.revoke_active(conn, key_id)
    if row is None:
        raise ProblemError(404, "Not Found", "API key not found", slug="not-found")
    return row


async def list_keys(engine: AsyncEngine, *, cursor: str | None, limit: int) -> Page[ApiKey]:
    async with tenant_transaction(engine) as conn:
        rows = await repo.list_active(conn, cursor, clamp(limit) + 1)
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more else None
    return Page[ApiKey](items=[ApiKey(**r) for r in rows], next_cursor=nxt)


async def create_key(engine: AsyncEngine, ctx: TenantContext, body: ApiKeyCreate) -> ApiKeyCreated:
    expires = (
        datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    )
    async with tenant_transaction(engine) as conn:
        created = await _insert(conn, ctx, body.name, canonical(list(body.roles)), expires)
        await emit_audit(
            conn,
            AuditEvent(
                action="apikey.created",
                object_type="api_key",
                object_id=str(created.id),
                after={"name": created.name, "roles": created.roles, "prefix": created.prefix},
            ),
        )
    return created


async def rotate_key(engine: AsyncEngine, ctx: TenantContext, key_id: uuid.UUID) -> ApiKeyCreated:
    """Revokes the key and issues a new secret with the same name, scope and expiry."""
    async with tenant_transaction(engine) as conn:
        old = await _revoke(conn, key_id)
        created = await _insert(conn, ctx, old.name, list(old.roles), old.expires_at)
        await repo.set_replaced_by(conn, key_id, created.id)
        await emit_audit(
            conn,
            AuditEvent(
                action="apikey.rotated",
                object_type="api_key",
                object_id=str(key_id),
                after={"replaced_by": str(created.id), "prefix": created.prefix},
            ),
        )
    return created


async def revoke_key(engine: AsyncEngine, key_id: uuid.UUID) -> None:
    async with tenant_transaction(engine) as conn:
        await _revoke(conn, key_id)
        await emit_audit(
            conn,
            AuditEvent(action="apikey.revoked", object_type="api_key", object_id=str(key_id)),
        )
