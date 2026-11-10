"""Runs (variant A/B), live progress (SSE), BOM versions, edits and export."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import text

from bomagent_api import idempotency
from bomagent_api.auth import OrgContext, still_authorized
from bomagent_api.authz import require
from bomagent_api.pagination import clamp, encode_cursor, page_clause
from bomagent_api.plans import check_new_run
from bomagent_api.routers.projects import deliver_now, get_project
from bomagent_api.schemas import (
    BomEnvelope,
    BomItemPatch,
    ModelOption,
    Page,
    Run,
    RunCreate,
    problem_responses,
)
from bomagent_bom.export import to_csv
from bomagent_bom.model import BomVersion, Provenance, ProvenanceKind
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import Message
from bomagent_common.outbox import enqueue
from bomagent_common.problems import ProblemError
from bomagent_llm.catalog import ModelNotAllowedError

router = APIRouter(
    prefix="/v1/runs",
    tags=["runs"],
    responses=problem_responses(400, 401, 403, 404, 409, 413, 422, 429),
)
models_router = APIRouter(
    prefix="/v1", tags=["runs"], responses=problem_responses(400, 401, 403, 422, 429)
)
RUN_COLS = (
    "id, project_id, variant, runtime, model_id, status, usage, error, created_by,"
    " created_at, started_at, finished_at"
)
TERMINAL = {"completed", "failed", "budget_exceeded"}
DEFAULT_RUNTIME = {"A": "langgraph_a", "B": "langgraph_b"}


async def get_run(conn: Any, run_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(f"SELECT {RUN_COLS} FROM runs.runs WHERE id = :i"),  # noqa: S608
            {"i": run_id},
        )
    ).first()
    if row is None:
        raise ProblemError(404, "Not Found", "run not found", slug="not-found")
    return dict(row._mapping)


@router.post("", status_code=202, summary="Start a BOM run (variant A or B)")
async def create_run(
    request: Request,
    ctx: OrgContext,
    body: RunCreate,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Run:
    require(ctx, "run.create")
    runtime = body.runtime or DEFAULT_RUNTIME[body.variant]
    if runtime.endswith("_a") != (body.variant == "A"):
        raise ProblemError(
            422,
            "Unprocessable Entity",
            f"runtime {runtime} does not implement variant {body.variant}",
            slug="runtime-variant",
        )
    try:
        request.app.state.catalog.get(
            body.model_id, allow_local=request.app.state.allow_local_models
        )
    except ModelNotAllowedError as exc:
        raise ProblemError(422, "Unprocessable Entity", str(exc), slug="model-not-allowed") from exc
    payload = body.model_dump(mode="json")
    async with tenant_transaction(request.app.state.engine) as conn:
        stored = await idempotency.replay(conn, idempotency_key, payload)
        if stored is not None:
            return Run(**stored)
        await get_project(conn, body.project_id)
        await check_new_run(conn)
        keys = (
            (
                await conn.execute(
                    text(
                        "SELECT object_key FROM projects.files WHERE project_id = :p"
                        " AND status = 'parsed' ORDER BY name"
                    ),
                    {"p": body.project_id},
                )
            )
            .scalars()
            .all()
        )
        if not keys:
            raise ProblemError(
                409,
                "Conflict",
                "upload design files and wait until they are checked before starting a run",
                slug="no-files",
            )
        rid = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO runs.runs (id, tenant_id, project_id, variant,"
                " runtime, model_id, requirements, created_by) VALUES (:i,"
                " app.current_tenant_id(), :p, :v, :rt, :m, CAST(:rq AS jsonb),"
                " :u)"
            ),
            {
                "i": rid,
                "p": body.project_id,
                "v": body.variant,
                "rt": runtime,
                "m": body.model_id,
                "rq": json.dumps(payload["requirements"]),
                "u": ctx.actor_id,
            },
        )
        run = Run(**await get_run(conn, rid))
        await emit_audit(
            conn,
            AuditEvent(
                action="run.created",
                object_type="run",
                object_id=str(rid),
                after={"variant": body.variant, "runtime": runtime, "model": body.model_id},
            ),
        )
        outbox_id = await enqueue(
            conn,
            "runs",
            Message.create(
                "run.requested",
                ctx,
                {
                    "run_id": str(rid),
                    "variant": body.variant,
                    "runtime": runtime,
                    "model_id": body.model_id,
                    "object_keys": list(keys),
                    "requirements": payload["requirements"],
                },
            ),
        )
        await idempotency.store(conn, idempotency_key, payload, 202, run.model_dump(mode="json"))
    await deliver_now(request, ctx.tenant_id, outbox_id)
    return run


@models_router.get("/models", summary="Models allowed for runs in this environment")
async def list_models(request: Request, ctx: OrgContext) -> list[ModelOption]:
    """The catalogue entries a run may use (enabled, verified, EU; local fakes only in
    local/test) - the same rule ``POST /v1/runs`` enforces."""
    require(ctx, "run.read")
    local = request.app.state.allow_local_models
    return [
        ModelOption(
            id=m.id,
            provider=m.provider,
            license_class=m.license_class.value,
            residency=m.residency,
            tier=m.tier,
        )
        for m in request.app.state.catalog.enabled("chat")
        if local or m.residency != "local"
    ]


@router.get("", summary="List runs")
async def list_runs(
    request: Request,
    ctx: OrgContext,
    cursor: str | None = None,
    limit: int = 25,
    project_id: uuid.UUID | None = None,
) -> Page[Run]:
    require(ctx, "run.read")
    params: dict[str, Any] = {"lim": clamp(limit) + 1}
    where = ""
    if project_id is not None:
        where, params["p"] = " AND project_id = :p", project_id
    sql = (
        f"SELECT {RUN_COLS} FROM runs.runs WHERE true{where}"  # noqa: S608
        f"{page_clause(cursor, params)} ORDER BY created_at DESC, id DESC LIMIT :lim"
    )
    async with tenant_transaction(request.app.state.engine) as conn:
        rows = [dict(r._mapping) for r in await conn.execute(text(sql), params)]
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more else None
    return Page[Run](items=[Run(**r) for r in rows], next_cursor=nxt)


@router.get("/{run_id}", summary="Get a run")
async def read_run(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> Run:
    require(ctx, "run.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        return Run(**await get_run(conn, run_id))


SSE_RECHECK_S = 5.0


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
    async with tenant_transaction(engine) as conn:
        await get_run(conn, run_id)
    interval = request.app.state.sse_interval_s

    async def stream() -> AsyncIterator[str]:
        last = None
        recheck_every = max(1, int(SSE_RECHECK_S / interval))
        for tick in range(int(request.app.state.sse_timeout_s / interval)):
            due = tick and tick % recheck_every == 0
            if due and not await still_authorized(request, ctx):
                yield 'event: end\ndata: {"status": "forbidden"}\n\n'
                return
            async with tenant_transaction(engine, ctx.tenant_id) as conn:
                row = (
                    await conn.execute(
                        text("SELECT status, usage, trace FROM runs.runs WHERE id = :i"),
                        {"i": run_id},
                    )
                ).one()
            snapshot = {"status": row.status, "usage": row.usage, "steps": len(row.trace)}
            if snapshot != last:
                yield f"event: progress\ndata: {json.dumps(snapshot)}\n\n"
                last = snapshot
            if row.status in TERMINAL:
                yield f"event: end\ndata: {json.dumps({'status': row.status})}\n\n"
                return
            await asyncio.sleep(interval)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
    )


async def latest_bom(conn: Any, run_id: uuid.UUID) -> tuple[uuid.UUID, int, BomVersion]:
    row = (
        await conn.execute(
            text(
                "SELECT id, version, content FROM bom.versions WHERE"
                " run_id = :r ORDER BY version DESC LIMIT 1"
            ),
            {"r": run_id},
        )
    ).first()
    if row is None:
        raise ProblemError(404, "Not Found", "no BOM for this run yet", slug="no-bom")
    return row.id, row.version, BomVersion.model_validate(row.content)


@router.get("/{run_id}/bom", summary="Latest BOM version of a run")
async def read_bom(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> BomEnvelope:
    require(ctx, "bom.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        _, version, bom = await latest_bom(conn, run_id)
    return BomEnvelope(run_id=run_id, version=version, bom=bom)


@router.get(
    "/{run_id}/bom.csv", summary="Export the latest BOM as CSV", response_class=PlainTextResponse
)
async def export_bom(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> PlainTextResponse:
    require(ctx, "bom.export")
    async with tenant_transaction(request.app.state.engine) as conn:
        _, version, bom = await latest_bom(conn, run_id)
        await emit_audit(
            conn,
            AuditEvent(
                action="bom.exported",
                object_type="run",
                object_id=str(run_id),
                after={"version": version},
            ),
        )
    return PlainTextResponse(
        to_csv(bom),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="bom-{run_id}-v{version}.csv"'},
    )


@router.patch("/{run_id}/bom/items/{line}", summary="Correct a BOM line (new version)")
async def patch_item(
    request: Request, ctx: OrgContext, run_id: uuid.UUID, line: int, body: BomItemPatch
) -> BomEnvelope:
    """Creates a new immutable BOM version with user provenance on the changed fields;
    a changed MPN is also stored as the organisation's knowledge (never global)."""
    require(ctx, "bom.edit")
    changes = body.model_dump(exclude_none=True, exclude={"reason"})
    if not changes:
        raise ProblemError(422, "Unprocessable Entity", "nothing to change", slug="empty-patch")
    async with tenant_transaction(request.app.state.engine) as conn:
        # serialise edits of one run: concurrent PATCHes would race for the next version
        await conn.execute(text("SELECT 1 FROM runs.runs WHERE id = :i FOR UPDATE"), {"i": run_id})
        parent_id, version, bom = await latest_bom(conn, run_id)
        idx = next((n for n, i in enumerate(bom.items) if i.line == line), None)
        if idx is None:
            raise ProblemError(404, "Not Found", f"line {line} not found", slug="not-found")
        item = bom.items[idx]
        before = {k: getattr(item, k) for k in changes}
        prov = Provenance(kind=ProvenanceKind.USER, user_id=ctx.actor_id, rationale=body.reason)
        new_item = item.model_copy(
            update={**changes, "provenance": {**item.provenance, **dict.fromkeys(changes, prov)}}
        )
        items = list(bom.items)
        items[idx] = new_item
        new_bom = bom.model_copy(update={"items": items})
        await conn.execute(
            text(
                "INSERT INTO bom.versions (id, tenant_id, run_id, version,"
                " parent_id, content, reason, created_by) VALUES (:i,"
                " app.current_tenant_id(), :r, :v, :p, CAST(:c AS jsonb), :why,"
                " :u)"
            ),
            {
                "i": uuid.uuid4(),
                "r": run_id,
                "v": version + 1,
                "p": parent_id,
                "c": new_bom.model_dump_json(),
                "why": body.reason,
                "u": ctx.actor_id,
            },
        )
        await emit_audit(
            conn,
            AuditEvent(
                action="bom.item_updated",
                object_type="bom_line",
                object_id=f"{run_id}:{line}",
                before=before,
                after=changes | {"reason": body.reason},
            ),
        )
        if changes.get("mpn"):
            await request.app.state.kb.add_correction(
                conn,
                mpn=changes["mpn"],
                manufacturer=changes.get("manufacturer", new_item.manufacturer),
                note=body.reason,
                attributes={"value": new_item.value, "footprint": new_item.footprint},
            )
    return BomEnvelope(run_id=run_id, version=version + 1, bom=new_bom)
