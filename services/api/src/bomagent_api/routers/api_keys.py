"""Organisation API keys for integrations (ARCHITECTURE §5): scoped roles, rotation,
only the SHA-256 of the secret in the database. Keys never get owner/admin roles."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response

from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.schemas import ApiKey, ApiKeyCreate, ApiKeyCreated, Page, problem_responses
from bomagent_api.services import api_keys as service

router = APIRouter(
    prefix="/v1/api-keys",
    tags=["api-keys"],
    responses=problem_responses(400, 401, 403, 404, 422, 429),
)


@router.get("", summary="List active API keys")
async def list_keys(
    request: Request, ctx: OrgContext, cursor: str | None = None, limit: int = 25
) -> Page[ApiKey]:
    require(ctx, "apikey.manage")
    return await service.list_keys(request.app.state.engine, cursor=cursor, limit=limit)


@router.post("", status_code=201, summary="Create an API key (the secret is shown once)")
async def create_key(request: Request, ctx: OrgContext, body: ApiKeyCreate) -> ApiKeyCreated:
    """Not replayable with Idempotency-Key on purpose: the response holds a secret."""
    require(ctx, "apikey.manage")
    return await service.create_key(request.app.state.engine, ctx, body)


@router.post("/{key_id}/rotate", status_code=201, summary="Rotate an API key")
async def rotate_key(request: Request, ctx: OrgContext, key_id: uuid.UUID) -> ApiKeyCreated:
    """Revokes the key and issues a new secret with the same name, scope and expiry."""
    require(ctx, "apikey.manage")
    return await service.rotate_key(request.app.state.engine, ctx, key_id)


@router.delete("/{key_id}", status_code=204, summary="Revoke an API key")
async def revoke_key(request: Request, ctx: OrgContext, key_id: uuid.UUID) -> Response:
    require(ctx, "apikey.manage")
    await service.revoke_key(request.app.state.engine, key_id)
    return Response(status_code=204)
