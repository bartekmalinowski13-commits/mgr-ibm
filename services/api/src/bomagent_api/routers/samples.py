"""Sample projects: add them to an organisation that was created before they existed."""

from __future__ import annotations

from fastapi import APIRouter, Request

from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.samples.seeding import seed_samples
from bomagent_api.schemas import SamplesAdded, problem_responses
from bomagent_common.problems import ProblemError

router = APIRouter(
    prefix="/v1/samples",
    tags=["samples"],
    responses=problem_responses(400, 401, 403, 404, 429),
)


@router.post("", summary="Add the sample projects to this organisation (owner)")
async def add_samples(request: Request, ctx: OrgContext) -> SamplesAdded:
    """Adds every sample project that is missing (idempotent: nothing is added twice) and
    queues its files for parsing. 404 when the deployment disabled samples
    (``BOMAGENT_SEED_SAMPLES``)."""
    require(ctx, "samples.add")
    if not request.app.state.samples_enabled:
        raise ProblemError(
            404, "Not Found", "sample projects are disabled on this deployment", slug="not-found"
        )
    result = await seed_samples(
        ctx,
        engine=request.app.state.engine,
        store=request.app.state.store,
        queues=request.app.state.queues,
        trigger="manual",
    )
    return SamplesAdded(added=result.added, existing=result.existing)
