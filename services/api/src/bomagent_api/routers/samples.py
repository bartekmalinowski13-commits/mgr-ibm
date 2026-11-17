"""Sample projects: add them to an organisation that was created before they existed."""

from __future__ import annotations

from fastapi import APIRouter, Request

from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.schemas import SamplesAdded, problem_responses
from bomagent_api.services import organizations as service

router = APIRouter(
    prefix="/v1/samples",
    tags=["samples"],
    responses=problem_responses(400, 401, 403, 404, 422, 429),
)


@router.post("", summary="Add the sample projects to this organisation (owner)")
async def add_samples(request: Request, ctx: OrgContext) -> SamplesAdded:
    """Adds every sample project that is missing (idempotent: nothing is added twice) and
    queues its files for parsing. 404 when the deployment disabled samples
    (``BOMAGENT_SEED_SAMPLES``)."""
    require(ctx, "samples.add")
    state = request.app.state
    return await service.add_samples(
        ctx,
        engine=state.engine,
        store=state.store,
        queues=state.queues,
        samples_enabled=state.samples_enabled,
    )
