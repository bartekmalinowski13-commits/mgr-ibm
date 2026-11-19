"""Runs (variant A/B), live progress (SSE), BOM versions, edits and export (HTTP only; the
use cases are in ``services.runs``)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Header, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response, StreamingResponse

from bomagent_api import idempotency
from bomagent_api.auth import OrgContext, still_authorized
from bomagent_api.authz import require
from bomagent_api.schemas import (
    BomDiffOut,
    BomEnvelope,
    BomItemPatch,
    BomVersionInfo,
    Evaluation,
    ModelOption,
    Page,
    Run,
    RunCreate,
    RunStep,
    problem_responses,
)
from bomagent_api.services import runs as service
from bomagent_api.services.runs import ExportedBom, RunDeps
from bomagent_api.sse_limits import StreamLimiter
from bomagent_common.problems import ProblemError

router = APIRouter(
    prefix="/v1/runs",
    tags=["runs"],
    responses=problem_responses(400, 401, 403, 404, 409, 413, 422, 429),
)
models_router = APIRouter(
    prefix="/v1", tags=["runs"], responses=problem_responses(400, 401, 403, 422, 429)
)
SSE_RECHECK_S = 5.0
MAX_REFERENCE = 1024 * 1024
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _deps(request: Request) -> RunDeps:
    state = request.app.state
    return RunDeps(
        engine=state.engine,
        queues=state.queues,
        kb=state.kb,
        catalog=state.catalog,
        allow_local_models=state.allow_local_models,
    )


def _is_demo(request: Request) -> bool:
    """True when the deployment answers with the fake model (``app.state.demo``)."""
    return bool(getattr(request.app.state, "demo", False))


@router.post("", status_code=202, summary="Start a BOM run (variant A or B)")
async def create_run(
    request: Request,
    ctx: OrgContext,
    body: RunCreate,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Run:
    require(ctx, "run.create")
    return await service.create_run(
        _deps(request),
        ctx,
        body,
        idempotency_key=idempotency_key,
        route=idempotency.route_of(request),
    )


@router.post("/{run_id}/rerun", status_code=202, summary="Run again with the same settings")
async def rerun(
    request: Request,
    ctx: OrgContext,
    run_id: uuid.UUID,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Run:
    """Starts a new run with the variant, runtime, model and requirements of ``run_id`` on
    the project's current parsed files (the run's own file snapshot is not kept) and a fresh
    knowledge-base snapshot (the same id as the original's when the KB is unchanged; ARCH-06).
    The model must still be allowed and the usual run quota applies."""
    require(ctx, "run.create")
    return await service.rerun(
        _deps(request),
        ctx,
        run_id,
        idempotency_key=idempotency_key,
        route=idempotency.route_of(request),
    )


@router.post("/{run_id}/cancel", summary="Cancel a queued or running run")
async def cancel_run(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> Run:
    """Marks the run ``failed`` with the error ``cancelled by user`` (the run status set has no
    separate value). A queued run is never started; a running run finishes its current step in
    the worker and the result is discarded (the worker only writes into a still-running row)."""
    require(ctx, "run.create")
    return await service.cancel_run(request.app.state.engine, run_id)


@models_router.get("/models", summary="Models allowed for runs in this environment")
async def list_models(request: Request, ctx: OrgContext) -> list[ModelOption]:
    """The catalogue entries a run may use (enabled, verified, EU; local fakes only in
    local/test) - the same rule ``POST /v1/runs`` enforces."""
    require(ctx, "run.read")
    return service.list_models(request.app.state.catalog, request.app.state.allow_local_models)


@router.get("", summary="List runs")
async def list_runs(
    request: Request,
    ctx: OrgContext,
    cursor: str | None = None,
    limit: int = 25,
    project_id: uuid.UUID | None = None,
) -> Page[Run]:
    require(ctx, "run.read")
    return await service.list_runs(
        request.app.state.engine, cursor=cursor, limit=limit, project_id=project_id
    )


@router.get("/{run_id}", summary="Get a run")
async def read_run(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> Run:
    require(ctx, "run.read")
    return await service.read_run(request.app.state.engine, run_id)


@router.get(
    "/{run_id}/events",
    summary="Live run progress (Server-Sent Events)",
    response_class=StreamingResponse,
)
async def run_events(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> StreamingResponse:
    """Polls the run row; access is re-checked every ``SSE_RECHECK_S`` so the stream of a
    removed member or revoked key ends."""
    require(ctx, "run.read")
    engine = request.app.state.engine
    await service.ensure_run_visible(engine, run_id)
    interval = request.app.state.sse_interval_s
    limiter = getattr(request.app.state, "sse_streams", None)
    if limiter is None:
        limiter = request.app.state.sse_streams = StreamLimiter()
    slot = limiter.acquire(ctx.tenant_id, ctx.actor_id)  # 429 beyond the cap (review M-3)

    async def stream() -> AsyncIterator[str]:
        try:
            last = None
            recheck_every = max(1, int(SSE_RECHECK_S / interval))
            for tick in range(int(request.app.state.sse_timeout_s / interval)):
                due = tick and tick % recheck_every == 0
                if due and not await still_authorized(request, ctx):
                    yield 'event: end\ndata: {"status": "forbidden"}\n\n'
                    return
                status, snapshot = await service.progress(engine, ctx.tenant_id, run_id)
                if snapshot != last:
                    yield f"event: progress\ndata: {json.dumps(snapshot)}\n\n"
                    last = snapshot
                if status in service.TERMINAL:
                    yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
                    return
                await asyncio.sleep(interval)
        finally:
            slot.release()

    body = stream()
    slot.release_with(body)  # a body that is never iterated still frees the slot
    return StreamingResponse(
        body, media_type="text/event-stream", headers={"Cache-Control": "no-store"}
    )


@router.get("/{run_id}/bom", summary="Latest BOM version of a run")
async def read_bom(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> BomEnvelope:
    require(ctx, "bom.read")
    version, bom = await service.read_bom(request.app.state.engine, run_id)
    return BomEnvelope(run_id=run_id, version=version, bom=bom, demo=_is_demo(request))


@router.get("/{run_id}/trace", summary="Steps of a finished run (agent graph nodes)")
async def read_trace(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> list[RunStep]:
    """Node name, duration and LLM calls per step; step details stay internal."""
    require(ctx, "run.read")
    return await service.read_trace(request.app.state.engine, run_id)


@router.post("/{run_id}/evaluation", summary="Evaluate the latest BOM against a reference BOM")
async def evaluate_bom(
    request: Request, ctx: OrgContext, run_id: uuid.UUID, reference: UploadFile
) -> Evaluation:
    """Metrics of the thesis (line P/R/F1, designators, field accuracy, MPN coverage)
    against a reference BOM CSV the user uploads. Nothing is stored except an audit
    event; the CSV is parsed as plain text (no design-file parser runs in the API)."""
    require(ctx, "bom.read")
    raw = await reference.read(MAX_REFERENCE + 1)
    if len(raw) > MAX_REFERENCE:
        raise ProblemError(
            413, "Payload Too Large", "reference BOM larger than 1 MB", slug="file-too-large"
        )
    return await service.evaluate_bom(request.app.state.engine, run_id, raw)


def _export_headers(
    run_id: uuid.UUID, exported: ExportedBom, ext: Literal["csv", "xlsx"]
) -> dict[str, str]:
    name = f"bom-{run_id}-v{exported.version}.{ext}"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if exported.kb_snapshot_id:
        headers["X-KB-Snapshot-Id"] = exported.kb_snapshot_id
    return headers


@router.get(
    "/{run_id}/bom.csv", summary="Export the latest BOM as CSV", response_class=PlainTextResponse
)
async def export_bom(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> PlainTextResponse:
    require(ctx, "bom.export")
    exported = await service.export_bom(
        request.app.state.engine, run_id, "csv", demo=_is_demo(request)
    )
    return PlainTextResponse(
        str(exported.content),
        media_type="text/csv",
        headers=_export_headers(run_id, exported, "csv"),
    )


@router.get(
    "/{run_id}/bom.xlsx",
    summary="Export the latest BOM as XLSX",
    response_class=Response,
    responses={200: {"content": {XLSX_TYPE: {}}, "description": "Excel workbook"}},
)
async def export_bom_xlsx(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> Response:
    require(ctx, "bom.export")
    exported = await service.export_bom(
        request.app.state.engine, run_id, "xlsx", demo=_is_demo(request)
    )
    return Response(
        cast(bytes, exported.content),
        media_type=XLSX_TYPE,
        headers=_export_headers(run_id, exported, "xlsx"),
    )


@router.get("/{run_id}/bom/versions", summary="Version history of a run's BOM")
async def list_bom_versions(
    request: Request, ctx: OrgContext, run_id: uuid.UUID
) -> list[BomVersionInfo]:
    """Newest first: the generated version 1 and every user correction after it."""
    require(ctx, "bom.read")
    return await service.list_bom_versions(request.app.state.engine, run_id)


@router.get("/{run_id}/bom/diff", summary="Differences between two BOM versions")
async def diff_bom_versions(
    request: Request, ctx: OrgContext, run_id: uuid.UUID, from_version: int, to_version: int
) -> BomDiffOut:
    require(ctx, "bom.read")
    return await service.diff_bom_versions(
        request.app.state.engine, run_id, from_version, to_version
    )


@router.get("/{run_id}/bom/versions/{version}", summary="One BOM version of a run")
async def read_bom_version(
    request: Request, ctx: OrgContext, run_id: uuid.UUID, version: int
) -> BomEnvelope:
    require(ctx, "bom.read")
    bom = await service.read_bom_version(request.app.state.engine, run_id, version)
    return BomEnvelope(run_id=run_id, version=version, bom=bom, demo=_is_demo(request))


@router.patch("/{run_id}/bom/items/{line}", summary="Correct a BOM line (new version)")
async def patch_item(
    request: Request, ctx: OrgContext, run_id: uuid.UUID, line: int, body: BomItemPatch
) -> BomEnvelope:
    """Creates a new immutable BOM version with user provenance on the changed fields;
    a changed MPN is also stored as the organisation's knowledge (never global)."""
    require(ctx, "bom.edit")
    version, bom = await service.patch_item(
        request.app.state.engine, request.app.state.kb, ctx, run_id, line, body
    )
    return BomEnvelope(run_id=run_id, version=version, bom=bom, demo=_is_demo(request))
