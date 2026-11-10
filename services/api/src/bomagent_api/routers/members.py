"""Organisation members and invitations.

Rules (ADR-0005 roles): owners and admins manage members; only owners grant, change or
remove the ``owner`` role; an organisation always keeps at least one owner. Invitations
carry a random secret shown once to the inviter (later sent by e-mail); the database
keeps only its SHA-256. Accepting requires a verified e-mail equal to the invited one.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_api.auth import CurrentPrincipal, OrgContext
from bomagent_api.authz import require
from bomagent_api.pagination import clamp, encode_cursor, page_clause
from bomagent_api.schemas import (
    Invitation,
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    Member,
    Membership,
    MemberUpdate,
    Page,
    problem_responses,
)
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext, require_tenant

router = APIRouter(
    prefix="/v1", tags=["members"], responses=problem_responses(400, 401, 403, 404, 409, 422, 429)
)
ROLE_ORDER = ("owner", "admin", "engineer", "reviewer", "viewer")
INVITATION_TTL = timedelta(days=7)
MEMBER_COLS = "user_sub, email, display_name, roles, created_at"
INVITE_COLS = "id, email, roles, status, invited_by, created_at, expires_at"


def canonical(roles: list[str]) -> list[str]:
    return [r for r in ROLE_ORDER if r in set(roles)]


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _forbid_owner_change(ctx: TenantContext) -> None:
    if "owner" not in ctx.roles:
        raise ProblemError(
            403, "Forbidden", "only owners can grant or change the owner role", slug="owner-only"
        )


async def _lock_members(conn: AsyncConnection) -> None:
    """Serialise membership changes of one tenant (owners demoting each other would
    otherwise deadlock on row locks taken in different orders)."""
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended('members:' || :t, 0))"),
        {"t": str(require_tenant().tenant_id)},
    )


async def _revoke_keys_of(conn: AsyncConnection, sub: str) -> int:
    """API keys a person created stop working when they lose admin rights."""
    revoked = await conn.execute(
        text(
            "UPDATE tenancy.api_keys SET revoked_at = now() WHERE created_by = :s"
            " AND revoked_at IS NULL AND tenant_id = app.current_tenant_id()"
        ),
        {"s": sub},
    )
    return revoked.rowcount


async def _member(conn: AsyncConnection, sub: str, *, lock: bool = False) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(
                f"SELECT {MEMBER_COLS} FROM tenancy.memberships"  # noqa: S608
                " WHERE user_sub = :s AND tenant_id = app.current_tenant_id()"
                + (" FOR UPDATE" if lock else "")
            ),
            {"s": sub},
        )
    ).first()
    if row is None:
        raise ProblemError(404, "Not Found", "member not found", slug="not-found")
    return dict(row._mapping)


async def _keeps_an_owner(conn: AsyncConnection, leaving: str) -> None:
    """Lock the owner rows so two owners cannot demote each other at the same time."""
    owners = (
        await conn.execute(
            text(
                "SELECT user_sub FROM tenancy.memberships WHERE 'owner' = ANY (roles)"
                " AND tenant_id = app.current_tenant_id() ORDER BY user_sub FOR UPDATE"
            )
        )
    ).scalars()
    if not set(owners) - {leaving}:
        raise ProblemError(
            409, "Conflict", "an organisation must keep at least one owner", slug="last-owner"
        )


# --------------------------------------------------------------------------- members
@router.get("/members", summary="List members of the organisation")
async def list_members(request: Request, ctx: OrgContext) -> Page[Member]:
    """All members (organisations are small; the page has no next cursor)."""
    require(ctx, "member.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        rows = await conn.execute(
            text(
                f"SELECT {MEMBER_COLS} FROM tenancy.memberships"  # noqa: S608
                " WHERE tenant_id = app.current_tenant_id() AND status = 'active'"
                " ORDER BY created_at, user_sub LIMIT 1000"
            )
        )
        items = [Member(**r._mapping) for r in rows]
    return Page[Member](items=items, next_cursor=None)


@router.patch("/members/{user_sub}", summary="Change the roles of a member")
async def update_member(
    request: Request, ctx: OrgContext, user_sub: str, body: MemberUpdate
) -> Member:
    require(ctx, "member.manage")
    roles = canonical(list(body.roles))
    async with tenant_transaction(request.app.state.engine) as conn:
        await _lock_members(conn)
        before = await _member(conn, user_sub, lock=True)
        was_owner = "owner" in before["roles"]
        if was_owner or "owner" in roles:
            _forbid_owner_change(ctx)
        if was_owner and "owner" not in roles:
            await _keeps_an_owner(conn, user_sub)
        await conn.execute(
            text(
                "UPDATE tenancy.memberships SET roles = :r"
                " WHERE user_sub = :s AND tenant_id = app.current_tenant_id()"
            ),
            {"r": roles, "s": user_sub},
        )
        revoked = 0
        if not {"owner", "admin"} & set(roles):
            revoked = await _revoke_keys_of(conn, user_sub)
        await emit_audit(
            conn,
            AuditEvent(
                action="member.roles_changed",
                object_type="member",
                object_id=user_sub,
                before={"roles": list(before["roles"])},
                after={"roles": roles, "api_keys_revoked": revoked},
            ),
        )
        return Member(**(before | {"roles": roles}))


@router.delete("/members/{user_sub}", status_code=204, summary="Remove a member")
async def remove_member(request: Request, ctx: OrgContext, user_sub: str) -> Response:
    require(ctx, "member.manage")
    async with tenant_transaction(request.app.state.engine) as conn:
        await _lock_members(conn)
        before = await _member(conn, user_sub, lock=True)
        if "owner" in before["roles"]:
            _forbid_owner_change(ctx)
            await _keeps_an_owner(conn, user_sub)
        await conn.execute(
            text(
                "DELETE FROM tenancy.memberships"
                " WHERE user_sub = :s AND tenant_id = app.current_tenant_id()"
            ),
            {"s": user_sub},
        )
        revoked = await _revoke_keys_of(conn, user_sub)
        await emit_audit(
            conn,
            AuditEvent(
                action="member.removed",
                object_type="member",
                object_id=user_sub,
                before={"roles": list(before["roles"]), "email": before["email"]},
                after={"api_keys_revoked": revoked},
            ),
        )
    return Response(status_code=204)


# --------------------------------------------------------------------------- invitations
@router.get("/invitations", summary="List pending invitations")
async def list_invitations(
    request: Request, ctx: OrgContext, cursor: str | None = None, limit: int = 25
) -> Page[Invitation]:
    require(ctx, "member.read")
    params: dict[str, Any] = {"lim": clamp(limit) + 1}
    sql = (
        f"SELECT {INVITE_COLS} FROM tenancy.invitations"  # noqa: S608
        " WHERE tenant_id = app.current_tenant_id() AND status = 'pending'"
        f"{page_clause(cursor, params)} ORDER BY created_at DESC, id DESC LIMIT :lim"
    )
    async with tenant_transaction(request.app.state.engine) as conn:
        rows = [dict(r._mapping) for r in await conn.execute(text(sql), params)]
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more else None
    return Page[Invitation](items=[Invitation(**r) for r in rows], next_cursor=nxt)


@router.post("/invitations", status_code=201, summary="Invite a person by e-mail")
async def create_invitation(
    request: Request, ctx: OrgContext, body: InvitationCreate
) -> InvitationCreated:
    """Not replayable with Idempotency-Key on purpose: the response holds a secret that
    must not be stored. A second pending invitation for the same e-mail is a 409."""
    require(ctx, "member.invite")
    roles = canonical(list(body.roles))
    if "owner" in roles:
        _forbid_owner_change(ctx)
    email = body.email.strip().lower()
    token = secrets.token_urlsafe(32)
    inv_id = uuid.uuid4()
    expires = datetime.now(UTC) + INVITATION_TTL
    async with tenant_transaction(request.app.state.engine) as conn:
        existing = (
            await conn.execute(
                text(
                    "SELECT 1 FROM tenancy.memberships WHERE lower(email) = :e"
                    " AND tenant_id = app.current_tenant_id()"
                ),
                {"e": email},
            )
        ).first()
        if existing is not None:
            raise ProblemError(409, "Conflict", "already a member", slug="already-member")
        await conn.execute(  # an expired invitation must not block a new one
            text(
                "UPDATE tenancy.invitations SET status = 'revoked' WHERE email = :e"
                " AND status = 'pending' AND expires_at <= now()"
                " AND tenant_id = app.current_tenant_id()"
            ),
            {"e": email},
        )
        row = (
            await conn.execute(
                text(
                    "INSERT INTO tenancy.invitations (id, tenant_id, email, roles, token_hash,"  # noqa: S608
                    " invited_by, expires_at) VALUES (:i, app.current_tenant_id(), :e, :r,"
                    " :h, :u, :x) ON CONFLICT DO NOTHING"
                    f" RETURNING {INVITE_COLS}"
                ),
                {
                    "i": inv_id,
                    "e": email,
                    "r": roles,
                    "h": token_hash(token),
                    "u": ctx.actor_id,
                    "x": expires,
                },
            )
        ).first()
        if row is None:
            raise ProblemError(
                409, "Conflict", "a pending invitation already exists", slug="invitation-pending"
            )
        await emit_audit(
            conn,
            AuditEvent(
                action="member.invited",
                object_type="invitation",
                object_id=str(inv_id),
                after={"email": email, "roles": roles, "expires_at": expires.isoformat()},
            ),
        )
    return InvitationCreated(**row._mapping, token=token)


@router.delete("/invitations/{invitation_id}", status_code=204, summary="Revoke an invitation")
async def revoke_invitation(
    request: Request, ctx: OrgContext, invitation_id: uuid.UUID
) -> Response:
    require(ctx, "member.invite")
    async with tenant_transaction(request.app.state.engine) as conn:
        row = (
            await conn.execute(
                text(
                    "UPDATE tenancy.invitations SET status = 'revoked' WHERE id = :i"
                    " AND status = 'pending' AND tenant_id = app.current_tenant_id()"
                    " RETURNING roles"
                ),
                {"i": invitation_id},
            )
        ).first()
        if row is None:
            raise ProblemError(404, "Not Found", "invitation not found", slug="not-found")
        if "owner" in row.roles:
            _forbid_owner_change(ctx)
        await emit_audit(
            conn,
            AuditEvent(
                action="member.invitation_revoked",
                object_type="invitation",
                object_id=str(invitation_id),
            ),
        )
    return Response(status_code=204)


@router.post("/invitations/accept", summary="Accept an invitation (join the organisation)")
async def accept_invitation(
    request: Request, principal: CurrentPrincipal, body: InvitationAccept
) -> Membership:
    if not principal.email_verified or not principal.email:
        raise ProblemError(
            403, "Forbidden", "a verified e-mail address is required", slug="email-not-verified"
        )
    engine = request.app.state.engine
    not_found = ProblemError(404, "Not Found", "invitation not found", slug="not-found")
    # invitee context: RLS shows only the pending invitation matching e-mail AND token
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "SELECT set_config('app.user_email', :e, true),"
                " set_config('app.invite_token_hash', :h, true)"
            ),
            {"e": principal.email.lower(), "h": token_hash(body.token)},
        )
        invite = (await conn.execute(text("SELECT id, tenant_id FROM tenancy.invitations"))).first()
    if invite is None:
        raise not_found
    tenant_id: uuid.UUID = invite.tenant_id
    async with tenant_transaction(engine, tenant_id) as conn:
        claimed = (
            await conn.execute(
                text(
                    "UPDATE tenancy.invitations SET status = 'accepted', accepted_by = :s,"
                    " accepted_at = now() WHERE id = :i AND status = 'pending'"
                    " AND expires_at > now() AND tenant_id = app.current_tenant_id()"
                    " RETURNING roles"
                ),
                {"s": principal.sub, "i": invite.id},
            )
        ).first()
        if claimed is None:  # revoked or accepted concurrently
            raise not_found
        roles = list(claimed.roles)
        inserted = (
            await conn.execute(
                text(
                    "INSERT INTO tenancy.memberships (tenant_id, user_sub, email,"
                    " display_name, roles) VALUES (app.current_tenant_id(), :s, :e, :d, :r)"
                    " ON CONFLICT (tenant_id, user_sub) DO NOTHING RETURNING user_sub"
                ),
                {"s": principal.sub, "e": principal.email.lower(), "d": principal.name, "r": roles},
            )
        ).first()
        if inserted is None:
            raise ProblemError(409, "Conflict", "already a member", slug="already-member")
        org = (
            await conn.execute(
                text("SELECT slug, name FROM tenancy.tenants WHERE id = app.current_tenant_id()")
            )
        ).one()
        ctx = TenantContext(tenant_id=tenant_id, actor_id=principal.sub, roles=frozenset(roles))
        await emit_audit(
            conn,
            AuditEvent(
                action="member.joined",
                object_type="member",
                object_id=principal.sub,
                after={"invitation_id": str(invite.id), "roles": roles},
            ),
            ctx,
        )
    return Membership(org_id=tenant_id, slug=org.slug, name=org.name, roles=roles)
