"""Organisation members and invitations.

Rules (ADR-0005 roles): owners and admins manage members; only owners grant, change or
remove the ``owner`` role; an organisation always keeps at least one owner. Invitations
carry a random secret shown once to the inviter and e-mailed to the invitee when a mailer
and ``invite_base_url`` are configured (UX-02); the database
keeps only its SHA-256. Accepting requires a verified e-mail equal to the invited one.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response

from bomagent_api.auth import CurrentPrincipal, OrgContext, require_verified_email
from bomagent_api.authz import require
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
from bomagent_api.services import members as service

router = APIRouter(
    prefix="/v1", tags=["members"], responses=problem_responses(400, 401, 403, 404, 409, 422, 429)
)


# --------------------------------------------------------------------------- members
@router.get("/members", summary="List members of the organisation")
async def list_members(
    request: Request, ctx: OrgContext, cursor: str | None = None, limit: int = 100
) -> Page[Member]:
    """Active members, oldest first (cursor-paginated; at most 100 per page)."""
    require(ctx, "member.read")
    return await service.list_members(request.app.state.engine, cursor=cursor, limit=limit)


@router.patch("/members/{user_sub}", summary="Change the roles of a member")
async def update_member(
    request: Request, ctx: OrgContext, user_sub: str, body: MemberUpdate
) -> Member:
    require(ctx, "member.manage")
    return await service.update_member(request.app.state.engine, ctx, user_sub, body)


@router.delete("/members/{user_sub}", status_code=204, summary="Remove a member")
async def remove_member(request: Request, ctx: OrgContext, user_sub: str) -> Response:
    require(ctx, "member.manage")
    await service.remove_member(request.app.state.engine, ctx, user_sub)
    return Response(status_code=204)


# --------------------------------------------------------------------------- invitations
@router.get("/invitations", summary="List pending invitations")
async def list_invitations(
    request: Request, ctx: OrgContext, cursor: str | None = None, limit: int = 25
) -> Page[Invitation]:
    require(ctx, "member.read")
    return await service.list_invitations(request.app.state.engine, cursor=cursor, limit=limit)


@router.post("/invitations", status_code=201, summary="Invite a person by e-mail")
async def create_invitation(
    request: Request, ctx: OrgContext, body: InvitationCreate
) -> InvitationCreated:
    """Not replayable with Idempotency-Key on purpose: the response holds a secret that
    must not be stored. A second pending invitation for the same e-mail is a 409."""
    require(ctx, "member.invite")
    state = request.app.state
    return await service.create_invitation(
        state.engine, state.mailer, state.invite_base_url, ctx, body
    )


@router.delete("/invitations/{invitation_id}", status_code=204, summary="Revoke an invitation")
async def revoke_invitation(
    request: Request, ctx: OrgContext, invitation_id: uuid.UUID
) -> Response:
    require(ctx, "member.invite")
    await service.revoke_invitation(request.app.state.engine, ctx, invitation_id)
    return Response(status_code=204)


@router.post("/invitations/accept", summary="Accept an invitation (join the organisation)")
async def accept_invitation(
    request: Request, principal: CurrentPrincipal, body: InvitationAccept
) -> Membership:
    await require_verified_email(request, principal)
    return await service.accept_invitation(
        request.app.state.engine,
        sub=principal.sub,
        email=principal.email,
        name=principal.name,
        token=body.token,
    )
