"""SQL of memberships and invitations (``tenancy.memberships``, ``tenancy.invitations``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, any_, delete, func, literal, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_api.repositories.tables import invitations, memberships, tenants

_MEMBER_COLS = (
    memberships.c.user_sub,
    memberships.c.email,
    memberships.c.display_name,
    memberships.c.roles,
    memberships.c.created_at,
)
_INVITE_COLS = (
    invitations.c.id,
    invitations.c.email,
    invitations.c.roles,
    invitations.c.status,
    invitations.c.invited_by,
    invitations.c.created_at,
    invitations.c.expires_at,
)
_THIS_TENANT = func.app.current_tenant_id()


async def lock_membership_changes(conn: AsyncConnection, tenant_id: uuid.UUID) -> None:
    """Serialise membership changes of one tenant (owners demoting each other would
    otherwise deadlock on row locks taken in different orders)."""
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended('members:' || :t, 0))"),
        {"t": str(tenant_id)},
    )


async def revoke_api_keys_of(conn: AsyncConnection, sub: str) -> int:
    """Revoke the API keys a person created; returns how many were still active."""
    revoked = await conn.execute(
        text(
            "UPDATE tenancy.api_keys SET revoked_at = now() WHERE created_by = :s"
            " AND revoked_at IS NULL AND tenant_id = app.current_tenant_id()"
        ),
        {"s": sub},
    )
    return int(revoked.rowcount)


async def get_member(
    conn: AsyncConnection, sub: str, *, lock: bool = False
) -> dict[str, Any] | None:
    stmt = select(*_MEMBER_COLS).where(
        memberships.c.user_sub == sub, memberships.c.tenant_id == _THIS_TENANT
    )
    if lock:
        stmt = stmt.with_for_update()
    row = (await conn.execute(stmt)).first()
    return dict(row._mapping) if row is not None else None


async def lock_owner_subs(conn: AsyncConnection) -> list[str]:
    """Subjects of the owners, rows locked so two owners cannot demote each other at once."""
    return list(
        (
            await conn.execute(
                select(memberships.c.user_sub)
                .where(
                    literal("owner") == any_(memberships.c.roles),
                    memberships.c.tenant_id == _THIS_TENANT,
                )
                .order_by(memberships.c.user_sub)
                .with_for_update()
            )
        ).scalars()
    )


async def list_active(conn: AsyncConnection, limit: int) -> list[dict[str, Any]]:
    rows = await conn.execute(
        select(*_MEMBER_COLS)
        .where(memberships.c.tenant_id == _THIS_TENANT, memberships.c.status == "active")
        .order_by(memberships.c.created_at, memberships.c.user_sub)
        .limit(limit)
    )
    return [dict(r._mapping) for r in rows]


async def set_roles(conn: AsyncConnection, sub: str, roles: list[str]) -> None:
    await conn.execute(
        update(memberships)
        .where(memberships.c.user_sub == sub, memberships.c.tenant_id == _THIS_TENANT)
        .values(roles=roles)
    )


async def delete_member(conn: AsyncConnection, sub: str) -> None:
    await conn.execute(
        delete(memberships).where(
            memberships.c.user_sub == sub, memberships.c.tenant_id == _THIS_TENANT
        )
    )


async def email_is_member(conn: AsyncConnection, email: str) -> bool:
    row = (
        await conn.execute(
            select(1).where(
                func.lower(memberships.c.email) == email, memberships.c.tenant_id == _THIS_TENANT
            )
        )
    ).first()
    return row is not None


async def display_name_of(conn: AsyncConnection, sub: str) -> str | None:
    """Display name of a member, falling back to the e-mail when it is empty."""
    name: str | None = (
        await conn.execute(
            select(
                func.coalesce(func.nullif(memberships.c.display_name, ""), memberships.c.email)
            ).where(memberships.c.user_sub == sub, memberships.c.tenant_id == _THIS_TENANT)
        )
    ).scalar_one_or_none()
    return name


async def insert_member_if_absent(
    conn: AsyncConnection, *, sub: str, email: str, display_name: str, roles: list[str]
) -> bool:
    """Join the organisation; False when the person already is a member."""
    row = (
        await conn.execute(
            pg_insert(memberships)
            .values(
                tenant_id=_THIS_TENANT,
                user_sub=sub,
                email=email,
                display_name=display_name,
                roles=roles,
            )
            .on_conflict_do_nothing(
                index_elements=[memberships.c.tenant_id, memberships.c.user_sub]
            )
            .returning(memberships.c.user_sub)
        )
    ).first()
    return row is not None


# ----------------------------------------------------------------------------- tenant
async def tenant_name(conn: AsyncConnection) -> str:
    return str(
        (
            await conn.execute(select(tenants.c.name).where(tenants.c.id == _THIS_TENANT))
        ).scalar_one()
    )


async def tenant_slug_and_name(conn: AsyncConnection) -> Any:
    return (
        await conn.execute(
            select(tenants.c.slug, tenants.c.name).where(tenants.c.id == _THIS_TENANT)
        )
    ).one()


# ------------------------------------------------------------------------- invitations
async def list_pending_invitations(
    conn: AsyncConnection, *, after: ColumnElement[bool] | None, limit: int
) -> list[dict[str, Any]]:
    stmt = select(*_INVITE_COLS).where(
        invitations.c.tenant_id == _THIS_TENANT, invitations.c.status == "pending"
    )
    if after is not None:
        stmt = stmt.where(after)
    stmt = stmt.order_by(invitations.c.created_at.desc(), invitations.c.id.desc()).limit(limit)
    return [dict(r._mapping) for r in await conn.execute(stmt)]


async def expire_pending_invitations(conn: AsyncConnection, email: str) -> None:
    """An expired invitation must not block a new one for the same e-mail."""
    await conn.execute(
        update(invitations)
        .where(
            invitations.c.email == email,
            invitations.c.status == "pending",
            invitations.c.expires_at <= func.now(),
            invitations.c.tenant_id == _THIS_TENANT,
        )
        .values(status="revoked")
    )


async def insert_invitation(
    conn: AsyncConnection,
    *,
    invitation_id: uuid.UUID,
    email: str,
    roles: list[str],
    token_hash: str,
    invited_by: str,
    expires_at: datetime,
) -> dict[str, Any] | None:
    """The new invitation, or None when a pending one for the e-mail already exists."""
    row = (
        await conn.execute(
            pg_insert(invitations)
            .values(
                id=invitation_id,
                tenant_id=_THIS_TENANT,
                email=email,
                roles=roles,
                token_hash=token_hash,
                invited_by=invited_by,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing()
            .returning(*_INVITE_COLS)
        )
    ).first()
    return dict(row._mapping) if row is not None else None


async def revoke_pending_invitation(conn: AsyncConnection, invitation_id: uuid.UUID) -> Any | None:
    """Revoke a pending invitation; returns its roles, or None when there is none."""
    return (
        await conn.execute(
            update(invitations)
            .where(
                invitations.c.id == invitation_id,
                invitations.c.status == "pending",
                invitations.c.tenant_id == _THIS_TENANT,
            )
            .values(status="revoked")
            .returning(invitations.c.roles)
        )
    ).first()


async def find_invitation_for_invitee(
    conn: AsyncConnection, *, email: str, token_hash: str
) -> Any | None:
    """Invitee context: RLS shows only the pending invitation matching e-mail AND token."""
    await conn.execute(
        text(
            "SELECT set_config('app.user_email', :e, true),"
            " set_config('app.invite_token_hash', :h, true)"
        ),
        {"e": email, "h": token_hash},
    )
    return (await conn.execute(select(invitations.c.id, invitations.c.tenant_id))).first()


async def claim_invitation(
    conn: AsyncConnection, invitation_id: uuid.UUID, accepted_by: str
) -> Any | None:
    """Mark a pending, unexpired invitation accepted; returns its roles or None."""
    return (
        await conn.execute(
            update(invitations)
            .where(
                invitations.c.id == invitation_id,
                invitations.c.status == "pending",
                invitations.c.expires_at > func.now(),
                invitations.c.tenant_id == _THIS_TENANT,
            )
            .values(status="accepted", accepted_by=accepted_by, accepted_at=func.now())
            .returning(invitations.c.roles)
        )
    ).first()
