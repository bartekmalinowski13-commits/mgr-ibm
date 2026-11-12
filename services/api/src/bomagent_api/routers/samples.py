"""Sample projects: add them to an organisation that was created before they existed."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Request

from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.plans import hit_rate_limit, plan_of
from bomagent_api.samples.seeding import seed_samples
from bomagent_api.schemas import SamplesAdded, problem_responses
from bomagent_common.db import tenant_transaction
from bomagent_common.problems import ProblemError

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
    async with tenant_transaction(request.app.state.engine, ctx.tenant_id) as conn:
        plan = await plan_of(conn)
        # each call may write files: a small extra limit on top of the per-user one
        await hit_rate_limit(conn, f"samples:{ctx.actor_id}", replace(plan, requests_per_minute=5))
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
