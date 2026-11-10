"""Organisation API keys for integrations (ARCHITECTURE §5): scoped roles, rotation,
only the SHA-256 of the secret in the database. Keys never get owner/admin roles."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_api.auth import API_KEY_PREFIX, OrgContext, api_key_hash
from bomagent_api.authz import require
from bomagent_api.pagination import clamp, encode_cursor, page_clause
from bomagent_api.routers.members import canonical
from bomagent_api.schemas import ApiKey, ApiKeyCreate, ApiKeyCreated, Page, problem_responses
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext

router = APIRouter(
    prefix="/v1/api-keys", tags=["api-keys"], responses=problem_responses(400, 401, 403, 404, 422)
)
COLS = "id, name, prefix, roles, created_by, created_at, expires_at, last_used_at"
ACTIVE = "revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())"


async def _insert(
    conn: AsyncConnection,
    ctx: TenantContext,
    name: str,
    roles: list[str],
    expires_at: datetime | None,
) -> ApiKeyCreated:
    key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    row = (
        await conn.execute(
            text(
                "INSERT INTO tenancy.api_keys (id, tenant_id, name, prefix, key_hash, roles,"  # noqa: S608
                " created_by, expires_at) VALUES (:i, app.current_tenant_id(), :n, :p, :h,"
                f" :r, :u, :x) RETURNING {COLS}"
            ),
            {
                "i": uuid.uuid4(),
                "n": name,
                "p": key[:12],
                "h": api_key_hash(key),
                "r": roles,
                "u": ctx.actor_id,
                "x": expires_at,
            },
        )
    ).one()
    return ApiKeyCreated(**row._mapping, key=key)


@router.get("", summary="List active API keys")
async def list_keys(
    request: Request, ctx: OrgContext, cursor: str | None = None, limit: int = 25
) -> Page[ApiKey]:
    require(ctx, "apikey.manage")
    params: dict[str, Any] = {"lim": clamp(limit) + 1}
    sql = (
        f"SELECT {COLS} FROM tenancy.api_keys WHERE tenant_id = app.current_tenant_id()"  # noqa: S608
        f" AND {ACTIVE}{page_clause(cursor, params)} ORDER BY created_at DESC, id DESC LIMIT :lim"
    )
    async with tenant_transaction(request.app.state.engine) as conn:
        rows = [dict(r._mapping) for r in await conn.execute(text(sql), params)]
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more else None
    return Page[ApiKey](items=[ApiKey(**r) for r in rows], next_cursor=nxt)


@router.post("", status_code=201, summary="Create an API key (the secret is shown once)")
async def create_key(request: Request, ctx: OrgContext, body: ApiKeyCreate) -> ApiKeyCreated:
    """Not replayable with Idempotency-Key on purpose: the response holds a secret."""
    require(ctx, "apikey.manage")
    expires = (
        datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    )
    async with tenant_transaction(request.app.state.engine) as conn:
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


async def _revoke(conn: AsyncConnection, key_id: uuid.UUID) -> Any:
    row = (
        await conn.execute(
            text(
                "UPDATE tenancy.api_keys SET revoked_at = now() WHERE id = :i"  # noqa: S608
                f" AND tenant_id = app.current_tenant_id() AND {ACTIVE}"
                " RETURNING name, roles, expires_at"
            ),
            {"i": key_id},
        )
    ).first()
    if row is None:
        raise ProblemError(404, "Not Found", "API key not found", slug="not-found")
    return row


@router.post("/{key_id}/rotate", status_code=201, summary="Rotate an API key")
async def rotate_key(request: Request, ctx: OrgContext, key_id: uuid.UUID) -> ApiKeyCreated:
    """Revokes the key and issues a new secret with the same name, scope and expiry."""
    require(ctx, "apikey.manage")
    async with tenant_transaction(request.app.state.engine) as conn:
        old = await _revoke(conn, key_id)
        created = await _insert(conn, ctx, old.name, list(old.roles), old.expires_at)
        await conn.execute(
            text("UPDATE tenancy.api_keys SET replaced_by = :n WHERE id = :i"),
            {"n": created.id, "i": key_id},
        )
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


@router.delete("/{key_id}", status_code=204, summary="Revoke an API key")
async def revoke_key(request: Request, ctx: OrgContext, key_id: uuid.UUID) -> Response:
    require(ctx, "apikey.manage")
    async with tenant_transaction(request.app.state.engine) as conn:
        await _revoke(conn, key_id)
        await emit_audit(
            conn,
            AuditEvent(action="apikey.revoked", object_type="api_key", object_id=str(key_id)),
        )
    return Response(status_code=204)
