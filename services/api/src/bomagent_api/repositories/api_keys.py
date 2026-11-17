"""SQL of organisation API keys (``tenancy.api_keys``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_api.pagination import page_clause

COLS = "id, name, prefix, roles, created_by, created_at, expires_at, last_used_at"
ACTIVE = "revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())"


async def insert_key(
    conn: AsyncConnection,
    *,
    name: str,
    prefix: str,
    key_hash: str,
    roles: list[str],
    created_by: str,
    expires_at: datetime | None,
) -> dict[str, Any]:
    row = (
        await conn.execute(
            # S608: ``COLS`` is a module constant (a fixed column list); values are bound
            text(
                "INSERT INTO tenancy.api_keys (id, tenant_id, name, prefix, key_hash, roles,"  # noqa: S608
                " created_by, expires_at) VALUES (:i, app.current_tenant_id(), :n, :p, :h,"
                f" :r, :u, :x) RETURNING {COLS}"
            ),
            {
                "i": uuid.uuid4(),
                "n": name,
                "p": prefix,
                "h": key_hash,
                "r": roles,
                "u": created_by,
                "x": expires_at,
            },
        )
    ).one()
    return dict(row._mapping)


async def list_active(
    conn: AsyncConnection, cursor: str | None, limit: int
) -> list[dict[str, Any]]:
    """Active keys, newest first; ``limit`` rows are fetched as given."""
    params: dict[str, Any] = {"lim": limit}
    # S608: ``COLS`` and ``ACTIVE`` are module constants (fixed column list and predicate);
    # the cursor and limit are bound parameters
    sql = (
        f"SELECT {COLS} FROM tenancy.api_keys WHERE tenant_id = app.current_tenant_id()"  # noqa: S608
        f" AND {ACTIVE}{page_clause(cursor, params)} ORDER BY created_at DESC, id DESC LIMIT :lim"
    )
    return [dict(r._mapping) for r in await conn.execute(text(sql), params)]


async def revoke_active(conn: AsyncConnection, key_id: uuid.UUID) -> Any | None:
    """Revoke an active key; returns its name, roles and expiry, or None when not found."""
    return (
        await conn.execute(
            # S608: ``ACTIVE`` is a module constant predicate; the key id is bound
            text(
                "UPDATE tenancy.api_keys SET revoked_at = now() WHERE id = :i"  # noqa: S608
                f" AND tenant_id = app.current_tenant_id() AND {ACTIVE}"
                " RETURNING name, roles, expires_at"
            ),
            {"i": key_id},
        )
    ).first()


async def set_replaced_by(conn: AsyncConnection, key_id: uuid.UUID, new_id: uuid.UUID) -> None:
    await conn.execute(
        text("UPDATE tenancy.api_keys SET replaced_by = :n WHERE id = :i"),
        {"n": new_id, "i": key_id},
    )
