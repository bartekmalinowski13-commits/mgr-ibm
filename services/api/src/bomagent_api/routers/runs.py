"""Runs (variant A/B), live progress (SSE), BOM versions, edits and export."""

from __future__ import annotations

import asyncio
import csv
import json
import math
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from sqlalchemy import text

from bomagent_api import idempotency
from bomagent_api.auth import OrgContext, still_authorized
from bomagent_api.authz import require
from bomagent_api.pagination import clamp, encode_cursor, page_clause
from bomagent_api.plans import check_new_run
from bomagent_api.routers.projects import deliver_now, get_project
from bomagent_api.schemas import (
    BomDiffOut,
    BomEnvelope,
    BomFieldChange,
    BomItemPatch,
    BomLineChange,
    BomVersionInfo,
    Counts,
    Evaluation,
    FieldAccuracy,
    ModelOption,
    Page,
    ReferenceDiff,
    Run,
    RunCreate,
    RunStep,
    problem_responses,
)
from bomagent_bom.diff import diff_versions
from bomagent_bom.export import to_csv, to_xlsx
from bomagent_bom.model import BomVersion, Provenance, ProvenanceKind, Requirements
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import Message
from bomagent_common.outbox import enqueue
from bomagent_common.problems import ProblemError
from bomagent_eval.metrics import evaluate
from bomagent_eval.reference import load_reference_csv
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
    " created_at, started_at, finished_at, kb_snapshot_id"
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


def check_model_allowed(request: Request, model_id: str) -> None:
    try:
        request.app.state.catalog.get(model_id, allow_local=request.app.state.allow_local_models)
    except ModelNotAllowedError as exc:
        raise ProblemError(422, "Unprocessable Entity", str(exc), slug="model-not-allowed") from exc


async def start_run(
    request: Request,
    ctx: OrgContext,
    conn: Any,
    *,
    project_id: uuid.UUID,
    variant: str,
    runtime: str,
    model_id: str,
    requirements: dict[str, Any],
    audit_extra: dict[str, Any] | None = None,
) -> tuple[Run, uuid.UUID]:
    """Insert a queued run for the project's parsed files and queue it (outbox). Shared by
    ``POST /v1/runs`` and re-execution; the caller delivers the outbox message after commit."""
    await get_project(conn, project_id)
    await check_new_run(conn)
    keys = (
        (
            await conn.execute(
                text(
                    "SELECT object_key FROM projects.files WHERE project_id = :p"
                    " AND status = 'parsed' ORDER BY name"
                ),
                {"p": project_id},
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
    # ADR-0008 / R10: pin the run to the tenant's knowledge base as it is now. The snapshot id
    # is a hash of the active documents, so an unchanged KB reuses the existing row.
    kb_snapshot_id = await request.app.state.kb.snapshot(conn)
    await conn.execute(
        text(
            "INSERT INTO runs.runs (id, tenant_id, project_id, variant,"
            " runtime, model_id, requirements, kb_snapshot_id, created_by) VALUES (:i,"
            " app.current_tenant_id(), :p, :v, :rt, :m, CAST(:rq AS jsonb),"
            " :k, :u)"
        ),
        {
            "i": rid,
            "p": project_id,
            "v": variant,
            "rt": runtime,
            "m": model_id,
            "rq": json.dumps(requirements),
            "k": kb_snapshot_id,
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
            after={
                "variant": variant,
                "runtime": runtime,
                "model": model_id,
                "kb_snapshot_id": kb_snapshot_id,
            }
            | (audit_extra or {}),
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
                "variant": variant,
                "runtime": runtime,
                "model_id": model_id,
                "object_keys": list(keys),
                "requirements": requirements,
                "kb_snapshot_id": kb_snapshot_id,
            },
        ),
    )
    return run, outbox_id


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
    check_model_allowed(request, body.model_id)
    payload = body.model_dump(mode="json")
    async with tenant_transaction(request.app.state.engine) as conn:
        stored = await idempotency.replay(
            conn, idempotency_key, payload, route=idempotency.route_of(request)
        )
        if stored is not None:
            return Run(**stored)
        run, outbox_id = await start_run(
            request,
            ctx,
            conn,
            project_id=body.project_id,
            variant=body.variant,
            runtime=runtime,
            model_id=body.model_id,
            requirements=payload["requirements"],
        )
        await idempotency.store(
            conn,
            idempotency_key,
            payload,
            202,
            run.model_dump(mode="json"),
            route=idempotency.route_of(request),
        )
    await deliver_now(request, ctx.tenant_id, outbox_id)
    return run


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
    payload = {"rerun_of": str(run_id)}
    async with tenant_transaction(request.app.state.engine) as conn:
        stored = await idempotency.replay(
            conn, idempotency_key, payload, route=idempotency.route_of(request)
        )
        if stored is not None:
            return Run(**stored)
        row = (
            await conn.execute(
                text(
                    "SELECT project_id, variant, runtime, model_id, requirements"
                    " FROM runs.runs WHERE id = :i"
                ),
                {"i": run_id},
            )
        ).first()
        if row is None:
            raise ProblemError(404, "Not Found", "run not found", slug="not-found")
        check_model_allowed(request, row.model_id)
        run, outbox_id = await start_run(
            request,
            ctx,
            conn,
            project_id=row.project_id,
            variant=row.variant,
            runtime=row.runtime,
            model_id=row.model_id,
            requirements=Requirements.model_validate(row.requirements).model_dump(mode="json"),
            audit_extra={"rerun_of": str(run_id)},
        )
        await idempotency.store(
            conn,
            idempotency_key,
            payload,
            202,
            run.model_dump(mode="json"),
            route=idempotency.route_of(request),
        )
    await deliver_now(request, ctx.tenant_id, outbox_id)
    return run


CANCELLED = "cancelled by user"


@router.post("/{run_id}/cancel", summary="Cancel a queued or running run")
async def cancel_run(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> Run:
    """Marks the run ``failed`` with the error ``cancelled by user`` (the run status set has no
    separate value). A queued run is never started; a running run finishes its current step in
    the worker and the result is discarded (the worker only writes into a still-running row)."""
    require(ctx, "run.create")
    async with tenant_transaction(request.app.state.engine) as conn:
        row = (
            await conn.execute(
                text("SELECT status FROM runs.runs WHERE id = :i FOR UPDATE"), {"i": run_id}
            )
        ).first()
        if row is None:
            raise ProblemError(404, "Not Found", "run not found", slug="not-found")
        if row.status not in ("queued", "running"):
            raise ProblemError(
                409,
                "Conflict",
                f"a {row.status} run cannot be cancelled",
                slug="run-not-cancellable",
            )
        await conn.execute(
            text(
                "UPDATE runs.runs SET status = 'failed', error = :e, finished_at = now()"
                " WHERE id = :i"
            ),
            {"e": CANCELLED, "i": run_id},
        )
        run = Run(**await get_run(conn, run_id))
        await emit_audit(
            conn,
            AuditEvent(
                action="run.cancelled",
                object_type="run",
                object_id=str(run_id),
                before={"status": row.status},
                after={"status": "failed", "error": CANCELLED},
            ),
        )
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
            snapshot = {
                "status": row.status,
                "usage": row.usage,
                "steps": len(row.trace),
                # the agent worker appends every finished step (live progress)
                "step": row.trace[-1].get("node") if row.trace else None,
            }
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


def _is_demo(request: Request) -> bool:
    """True when the deployment answers with the fake model (``app.state.demo``)."""
    return bool(getattr(request.app.state, "demo", False))


@router.get("/{run_id}/bom", summary="Latest BOM version of a run")
async def read_bom(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> BomEnvelope:
    require(ctx, "bom.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        _, version, bom = await latest_bom(conn, run_id)
    return BomEnvelope(run_id=run_id, version=version, bom=bom, demo=_is_demo(request))


@router.get("/{run_id}/trace", summary="Steps of a finished run (agent graph nodes)")
async def read_trace(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> list[RunStep]:
    """Node name, duration and LLM calls per step; step details stay internal."""
    require(ctx, "run.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        row = (
            await conn.execute(text("SELECT trace FROM runs.runs WHERE id = :i"), {"i": run_id})
        ).first()
    if row is None:
        raise ProblemError(404, "Not Found", "run not found", slug="not-found")
    return [
        RunStep(
            node=str(s.get("node", "")),
            duration_s=float(s.get("duration_s", 0.0)),
            llm_calls=int(s.get("llm_calls", 0)),
        )
        for s in row.trace or []
    ]


MAX_REFERENCE = 1024 * 1024


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
    try:
        ref_items = load_reference_csv(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, csv.Error) as exc:
        raise ProblemError(
            422,
            "Unprocessable Entity",
            "the reference must be a CSV BOM with a designator column (e.g. Reference)",
            slug="invalid-reference",
        ) from exc
    if not ref_items:
        raise ProblemError(
            422, "Unprocessable Entity", "the reference BOM has no lines", slug="invalid-reference"
        )
    async with tenant_transaction(request.app.state.engine) as conn:
        _, version, bom = await latest_bom(conn, run_id)
        report = evaluate(bom, ref_items, design=bom.design_name, variant=bom.variant)
        summary = {k: (None if math.isnan(v) else round(v, 6)) for k, v in report.summary().items()}
        await emit_audit(
            conn,
            AuditEvent(
                action="bom.evaluated",
                object_type="run",
                object_id=str(run_id),
                after={
                    "version": version,
                    "reference_lines": len(ref_items),
                    "line_f1": summary.get("line_f1"),
                },
            ),
        )
    return Evaluation(
        run_id=run_id,
        version=version,
        reference_lines=len(ref_items),
        summary=summary,
        lines=Counts(**report.lines.model_dump()),
        designators=Counts(**report.designators.model_dump()),
        fields={k: FieldAccuracy(**v.model_dump()) for k, v in report.fields.items()},
        diffs=[ReferenceDiff(**d.model_dump()) for d in report.diffs],
    )


def _export_headers(
    run_id: uuid.UUID, version: int, ext: str, kb_snapshot_id: str | None
) -> dict[str, str]:
    headers = {"Content-Disposition": f'attachment; filename="bom-{run_id}-v{version}.{ext}"'}
    if kb_snapshot_id:
        headers["X-KB-Snapshot-Id"] = kb_snapshot_id
    return headers


@router.get(
    "/{run_id}/bom.csv", summary="Export the latest BOM as CSV", response_class=PlainTextResponse
)
async def export_bom(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> PlainTextResponse:
    require(ctx, "bom.export")
    async with tenant_transaction(request.app.state.engine) as conn:
        _, version, bom = await latest_bom(conn, run_id)
        snapshot = (await get_run(conn, run_id))["kb_snapshot_id"]
        await emit_audit(
            conn,
            AuditEvent(
                action="bom.exported",
                object_type="run",
                object_id=str(run_id),
                after={"version": version, "kb_snapshot_id": snapshot},
            ),
        )
    return PlainTextResponse(
        to_csv(bom, demo=_is_demo(request), kb_snapshot_id=snapshot),
        media_type="text/csv",
        headers=_export_headers(run_id, version, "csv", snapshot),
    )


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get(
    "/{run_id}/bom.xlsx",
    summary="Export the latest BOM as XLSX",
    response_class=Response,
    responses={200: {"content": {XLSX_TYPE: {}}, "description": "Excel workbook"}},
)
async def export_bom_xlsx(request: Request, ctx: OrgContext, run_id: uuid.UUID) -> Response:
    require(ctx, "bom.export")
    async with tenant_transaction(request.app.state.engine) as conn:
        _, version, bom = await latest_bom(conn, run_id)
        snapshot = (await get_run(conn, run_id))["kb_snapshot_id"]
        await emit_audit(
            conn,
            AuditEvent(
                action="bom.exported",
                object_type="run",
                object_id=str(run_id),
                after={"version": version, "format": "xlsx", "kb_snapshot_id": snapshot},
            ),
        )
    return Response(
        to_xlsx(bom, demo=_is_demo(request), kb_snapshot_id=snapshot),
        media_type=XLSX_TYPE,
        headers=_export_headers(run_id, version, "xlsx", snapshot),
    )


async def bom_at(conn: Any, run_id: uuid.UUID, version: int) -> BomVersion:
    row = (
        await conn.execute(
            text("SELECT content FROM bom.versions WHERE run_id = :r AND version = :v"),
            {"r": run_id, "v": version},
        )
    ).first()
    if row is None:
        raise ProblemError(404, "Not Found", f"version {version} not found", slug="not-found")
    return BomVersion.model_validate(row.content)


@router.get("/{run_id}/bom/versions", summary="Version history of a run's BOM")
async def list_bom_versions(
    request: Request, ctx: OrgContext, run_id: uuid.UUID
) -> list[BomVersionInfo]:
    """Newest first: the generated version 1 and every user correction after it."""
    require(ctx, "bom.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        await get_run(conn, run_id)
        rows = await conn.execute(
            text(
                "SELECT v.version, p.version AS parent_version, v.reason, v.created_by,"
                " v.created_at, jsonb_array_length(v.content->'items') AS lines,"
                " jsonb_array_length(COALESCE(v.content->'findings', '[]'::jsonb)) AS findings"
                " FROM bom.versions v LEFT JOIN bom.versions p ON p.id = v.parent_id"
                " WHERE v.run_id = :r ORDER BY v.version DESC"
            ),
            {"r": run_id},
        )
        return [BomVersionInfo(**dict(r._mapping)) for r in rows]


@router.get("/{run_id}/bom/diff", summary="Differences between two BOM versions")
async def diff_bom_versions(
    request: Request, ctx: OrgContext, run_id: uuid.UUID, from_version: int, to_version: int
) -> BomDiffOut:
    require(ctx, "bom.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        old = await bom_at(conn, run_id, from_version)
        new = await bom_at(conn, run_id, to_version)
    diff = diff_versions(old, new)
    return BomDiffOut(
        run_id=run_id,
        from_version=from_version,
        to_version=to_version,
        added=diff.added,
        removed=diff.removed,
        changed=[
            BomLineChange(
                line=c.line,
                refdes=c.refdes,
                fields=[BomFieldChange(**f.model_dump()) for f in c.fields],
            )
            for c in diff.changed
        ],
    )


@router.get("/{run_id}/bom/versions/{version}", summary="One BOM version of a run")
async def read_bom_version(
    request: Request, ctx: OrgContext, run_id: uuid.UUID, version: int
) -> BomEnvelope:
    require(ctx, "bom.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        bom = await bom_at(conn, run_id, version)
    return BomEnvelope(run_id=run_id, version=version, bom=bom, demo=_is_demo(request))


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
    return BomEnvelope(run_id=run_id, version=version + 1, bom=new_bom, demo=_is_demo(request))
