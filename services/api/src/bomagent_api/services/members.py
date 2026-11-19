"""Organisation members and invitations (ARCH-04).

Rules (ADR-0005 roles): owners and admins manage members; only owners grant, change or
remove the ``owner`` role; an organisation always keeps at least one owner. Invitations
carry a random secret shown once to the inviter and e-mailed to the invitee when a mailer
and ``invite_base_url`` are configured (UX-02); the database
keeps only its SHA-256. Accepting requires a verified e-mail equal to the invited one.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bomagent_api.pagination import (
    MAX_LIMIT,
    clamp,
    decode_key_cursor,
    encode_cursor,
    encode_key_cursor,
    page_filter,
)
from bomagent_api.repositories import members as repo
from bomagent_api.repositories.tables import invitations
from bomagent_api.schemas import (
    Invitation,
    InvitationCreate,
    InvitationCreated,
    Member,
    Membership,
    MemberUpdate,
    Page,
)
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.mailer import Mailer, MailError, invitation_mail
from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext, require_tenant

log = get_logger(__name__)
ROLE_ORDER = ("owner", "admin", "engineer", "reviewer", "viewer")
INVITATION_TTL = timedelta(days=7)


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
    await repo.lock_membership_changes(conn, require_tenant().tenant_id)


async def _member(conn: AsyncConnection, sub: str, *, lock: bool = False) -> dict[str, Any]:
    row = await repo.get_member(conn, sub, lock=lock)
    if row is None:
        raise ProblemError(404, "Not Found", "member not found", slug="not-found")
    return row


async def _keeps_an_owner(conn: AsyncConnection, leaving: str) -> None:
    """Lock the owner rows so two owners cannot demote each other at the same time."""
    owners = await repo.lock_owner_subs(conn)
    if not set(owners) - {leaving}:
        raise ProblemError(
            409, "Conflict", "an organisation must keep at least one owner", slug="last-owner"
        )


# --------------------------------------------------------------------------- members
async def list_members(
    engine: AsyncEngine, *, cursor: str | None = None, limit: int = MAX_LIMIT
) -> Page[Member]:
    """Active members, oldest first, cursor-paginated on ``(created_at, user_sub)``."""
    after = decode_key_cursor(cursor)
    async with tenant_transaction(engine) as conn:
        rows = await repo.list_active(conn, clamp(limit) + 1, after)
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    nxt = encode_key_cursor(rows[-1]["created_at"], rows[-1]["user_sub"]) if more else None
    return Page[Member](items=[Member(**r) for r in rows], next_cursor=nxt)


async def update_member(
    engine: AsyncEngine, ctx: TenantContext, user_sub: str, body: MemberUpdate
) -> Member:
    roles = canonical(list(body.roles))
    async with tenant_transaction(engine) as conn:
        await _lock_members(conn)
        before = await _member(conn, user_sub, lock=True)
        was_owner = "owner" in before["roles"]
        if was_owner or "owner" in roles:
            _forbid_owner_change(ctx)
        if was_owner and "owner" not in roles:
            await _keeps_an_owner(conn, user_sub)
        await repo.set_roles(conn, user_sub, roles)
        revoked = 0
        if not {"owner", "admin"} & set(roles):
            revoked = await repo.revoke_api_keys_of(conn, user_sub)
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


async def remove_member(engine: AsyncEngine, ctx: TenantContext, user_sub: str) -> None:
    async with tenant_transaction(engine) as conn:
        await _lock_members(conn)
        before = await _member(conn, user_sub, lock=True)
        if "owner" in before["roles"]:
            _forbid_owner_change(ctx)
            await _keeps_an_owner(conn, user_sub)
        await repo.delete_member(conn, user_sub)
        revoked = await repo.revoke_api_keys_of(conn, user_sub)
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


# --------------------------------------------------------------------------- invitations
async def list_invitations(
    engine: AsyncEngine, *, cursor: str | None, limit: int
) -> Page[Invitation]:
    after = page_filter(cursor, invitations.c.created_at, invitations.c.id)
    async with tenant_transaction(engine) as conn:
        rows = await repo.list_pending_invitations(conn, after=after, limit=clamp(limit) + 1)
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more else None
    return Page[Invitation](items=[Invitation(**r) for r in rows], next_cursor=nxt)


async def create_invitation(
    engine: AsyncEngine,
    mailer: Mailer,
    invite_base_url: str,
    ctx: TenantContext,
    body: InvitationCreate,
) -> InvitationCreated:
    """Not replayable with Idempotency-Key on purpose: the response holds a secret that
    must not be stored. A second pending invitation for the same e-mail is a 409."""
    roles = canonical(list(body.roles))
    if "owner" in roles:
        _forbid_owner_change(ctx)
    email = body.email.strip().lower()
    token = secrets.token_urlsafe(32)
    inv_id = uuid.uuid4()
    expires = datetime.now(UTC) + INVITATION_TTL
    async with tenant_transaction(engine) as conn:
        if await repo.email_is_member(conn, email):
            raise ProblemError(409, "Conflict", "already a member", slug="already-member")
        await repo.expire_pending_invitations(conn, email)
        row = await repo.insert_invitation(
            conn,
            invitation_id=inv_id,
            email=email,
            roles=roles,
            token_hash=token_hash(token),
            invited_by=ctx.actor_id,
            expires_at=expires,
        )
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
        org_name = await repo.tenant_name(conn)
        inviter = await repo.display_name_of(conn, ctx.actor_id)
    await _send_invitation_email(
        engine,
        mailer,
        invite_base_url,
        inv_id,
        email,
        token,
        org_name=org_name,
        inviter=inviter or "BOM Agent",
    )
    return InvitationCreated(**row, token=token)


async def _send_invitation_email(
    engine: AsyncEngine,
    mailer: Mailer,
    base: str,
    inv_id: uuid.UUID,
    email: str,
    token: str,
    *,
    org_name: str,
    inviter: str,
) -> None:
    """Best effort after commit: a relay outage must not lose the invitation (the inviter
    still holds the token). The outcome is audited; the token is never logged."""
    if not base:
        return
    mail = invitation_mail(
        to=email,
        org_name=org_name,
        inviter=inviter,
        link=f"{base}/invite/{token}",
        days=INVITATION_TTL.days,
    )
    outcome = "sent"
    try:
        await mailer.send(mail)
    except MailError as exc:
        outcome = "failed"
        log.warning("invitation.email_failed", invitation_id=str(inv_id), error=str(exc))
    except Exception as exc:  # the invitation is committed: any mailer bug is a failed send
        outcome = "failed"
        log.warning("invitation.email_failed", invitation_id=str(inv_id), error=type(exc).__name__)
    async with tenant_transaction(engine) as conn:
        await emit_audit(
            conn,
            AuditEvent(
                action="member.invitation_emailed",
                object_type="invitation",
                object_id=str(inv_id),
                after={"email": email, "outcome": outcome},
            ),
        )


async def revoke_invitation(
    engine: AsyncEngine, ctx: TenantContext, invitation_id: uuid.UUID
) -> None:
    async with tenant_transaction(engine) as conn:
        row = await repo.revoke_pending_invitation(conn, invitation_id)
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


async def accept_invitation(
    engine: AsyncEngine, *, sub: str, email: str, name: str, token: str
) -> Membership:
    """Join the organisation of the invitation matching the verified e-mail and the token."""
    not_found = ProblemError(404, "Not Found", "invitation not found", slug="not-found")
    # invitee context: RLS shows only the pending invitation matching e-mail AND token
    async with engine.begin() as conn:
        invite = await repo.find_invitation_for_invitee(
            conn, email=email.lower(), token_hash=token_hash(token)
        )
    if invite is None:
        raise not_found
    tenant_id: uuid.UUID = invite.tenant_id
    async with tenant_transaction(engine, tenant_id) as conn:
        claimed = await repo.claim_invitation(conn, invite.id, sub)
        if claimed is None:  # revoked or accepted concurrently
            raise not_found
        roles = list(claimed.roles)
        joined = await repo.insert_member_if_absent(
            conn, sub=sub, email=email.lower(), display_name=name, roles=roles
        )
        if not joined:
            raise ProblemError(409, "Conflict", "already a member", slug="already-member")
        org = await repo.tenant_slug_and_name(conn)
        ctx = TenantContext(tenant_id=tenant_id, actor_id=sub, roles=frozenset(roles))
        await emit_audit(
            conn,
            AuditEvent(
                action="member.joined",
                object_type="member",
                object_id=sub,
                after={"invitation_id": str(invite.id), "roles": roles},
            ),
            ctx,
        )
    return Membership(org_id=tenant_id, slug=org.slug, name=org.name, roles=roles)
