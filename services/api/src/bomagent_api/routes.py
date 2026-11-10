"""REST API v1: projects, designs (upload), runs (+SSE), BOM, audit (ADR-0015).

Conventions: problem+json errors (RFC 9457), cursor pagination, ``Idempotency-Key`` for
run creation, 404 for objects of other tenants (RLS makes them invisible), an audit event
for every mutation (ADR-0011).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_api.auth import CAN_AUDIT, CAN_READ, CAN_WRITE, Authenticator, require, unauthorized
from bomagent_bom.model import Requirements
from bomagent_common import records
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import Message, Queue
from bomagent_common.problems import ProblemError
from bomagent_common.storage import ObjectStore, tenant_key
from bomagent_common.tenancy import TenantContext, tenant_scope
from bomagent_llm.catalog import Catalog, ModelNotAllowedError

DESIGN_UPLOADED = "design.uploaded"
RUN_REQUESTED = "run.requested"
_FILENAME = r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$"
T = TypeVar("T")


@dataclass
class ApiServices:
    engine: AsyncEngine
    store: ObjectStore
    ingest_queue: Queue
    runs_queue: Queue
    authenticator: Authenticator
    catalog: Catalog
    allow_local_models: bool = False
    sse_poll_seconds: float = 1.0
    kb_queue: Queue | None = None  # knowledge-base indexing (kb-indexer)


def services(request: Request) -> ApiServices:
    svc: ApiServices = request.app.state.services
    return svc


async def current_context(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_request_id: Annotated[str | None, Header()] = None,
) -> TenantContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise unauthorized()
    ctx = services(request).authenticator.authenticate(authorization[7:].strip())
    rid = x_request_id or str(uuid.uuid4())
    return TenantContext(ctx.tenant_id, ctx.actor_id, ctx.actor_type, ctx.roles, rid)


Ctx = Annotated[TenantContext, Depends(current_context)]
Svc = Annotated[ApiServices, Depends(services)]


def not_found(kind: str) -> ProblemError:
    return ProblemError(404, "Not Found", f"{kind} not found", slug="not-found")


def conflict(detail: str) -> ProblemError:
    return ProblemError(409, "Conflict", detail, slug="conflict")


# ------------------------------------------------------------------ schemas
class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectIn(_In):
    name: str = Field(min_length=1, max_length=200)


class Project(BaseModel):
    id: uuid.UUID
    name: str
    created_by: str
    created_at: datetime


class Page(BaseModel, Generic[T]):  # noqa: UP046 - pydantic generic model
    items: list[T]
    next_cursor: str | None = None


class DesignIn(_In):
    filenames: list[Annotated[str, Field(pattern=_FILENAME)]] = Field(min_length=1, max_length=50)


class UploadTarget(BaseModel):
    filename: str
    url: str
    method: Literal["PUT"] = "PUT"


class Design(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    filenames: list[str]
    source_format: str | None = None
    components: int | None = None
    confidence: float | None = None
    limitations: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime


class DesignCreated(Design):
    uploads: list[UploadTarget]


class RunIn(_In):
    design_id: uuid.UUID
    variant: Literal["A", "B", "A-sdk"] = "B"
    model_id: str
    requirements: Requirements = Field(default_factory=Requirements)
    budget: dict[str, Any] | None = None


class Run(BaseModel):
    id: uuid.UUID
    design_id: uuid.UUID
    variant: str
    model_id: str
    status: str
    usage: dict[str, Any] | None = None
    error: str | None = None
    created_by: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AuditEntry(BaseModel):
    seq: int
    occurred_at: datetime
    actor_type: str
    actor_id: str
    action: str
    object_type: str
    object_id: str
    hash: str


def _design(row: dict[str, Any]) -> Design:
    return Design.model_validate(row | {"limitations": row.get("limitations") or []})


def _source_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


router = APIRouter(prefix="/v1")


# ------------------------------------------------------------------ projects
@router.post("/projects", status_code=201, response_model=Project, tags=["projects"])
async def create_project(body: ProjectIn, request: Request, ctx: Ctx, svc: Svc) -> Project:
    require(*CAN_WRITE)(ctx)
    async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
        row = await records.insert_project(conn, ctx.tenant_id, body.name, ctx.actor_id)
        await emit_audit(
            conn,
            AuditEvent(
                action="project.create",
                object_type="project",
                object_id=str(row["id"]),
                after={"name": body.name},
                source_ip=_source_ip(request),
            ),
            ctx,
        )
    return Project.model_validate(row)


@router.get("/projects", response_model=Page[Project], tags=["projects"])
async def list_projects(
    ctx: Ctx, svc: Svc, limit: Annotated[int, Query(ge=1, le=100)] = 20, cursor: str | None = None
) -> Page[Project]:
    require(*CAN_READ)(ctx)
    try:
        async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
            rows, nxt = await records.list_projects(conn, limit, cursor)
    except ValueError as exc:
        raise ProblemError(400, "Bad Request", str(exc), slug="bad-cursor") from exc
    return Page[Project](items=[Project.model_validate(r) for r in rows], next_cursor=nxt)


# ------------------------------------------------------------------ designs
@router.post(
    "/projects/{project_id}/designs",
    status_code=201,
    response_model=DesignCreated,
    tags=["designs"],
)
async def create_design(
    project_id: uuid.UUID, body: DesignIn, request: Request, ctx: Ctx, svc: Svc
) -> DesignCreated:
    require(*CAN_WRITE)(ctx)
    if len(set(body.filenames)) != len(body.filenames):
        raise ProblemError(422, "Unprocessable Content", "duplicate file names", slug="validation")
    async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
        if await records.get_project(conn, project_id) is None:
            raise not_found("project")
        row = await records.insert_design(
            conn, ctx.tenant_id, project_id, body.filenames, ctx.actor_id
        )
        await emit_audit(
            conn,
            AuditEvent(
                action="design.create",
                object_type="design",
                object_id=str(row["id"]),
                after={"filenames": body.filenames},
                source_ip=_source_ip(request),
            ),
            ctx,
        )
    with tenant_scope(ctx):
        uploads = [
            UploadTarget(
                filename=f,
                url=await svc.store.presign_put(
                    tenant_key(ctx.tenant_id, "designs", str(row["id"]), "files", f)
                ),
            )
            for f in body.filenames
        ]
    return DesignCreated.model_validate(_design(row).model_dump() | {"uploads": uploads})


@router.get("/projects/{project_id}/designs", response_model=Page[Design], tags=["designs"])
async def list_designs(
    project_id: uuid.UUID,
    ctx: Ctx,
    svc: Svc,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> Page[Design]:
    require(*CAN_READ)(ctx)
    try:
        async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
            if await records.get_project(conn, project_id) is None:
                raise not_found("project")
            rows, nxt = await records.list_designs(conn, project_id, limit, cursor)
    except ValueError as exc:
        raise ProblemError(400, "Bad Request", str(exc), slug="bad-cursor") from exc
    return Page[Design](items=[_design(r) for r in rows], next_cursor=nxt)


@router.post(
    "/designs/{design_id}/complete", status_code=202, response_model=Design, tags=["designs"]
)
async def complete_upload(design_id: uuid.UUID, request: Request, ctx: Ctx, svc: Svc) -> Design:
    """Mark the upload finished and queue parsing in the sandboxed ingest worker."""
    require(*CAN_WRITE)(ctx)
    async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
        if await records.get_design(conn, design_id) is None:
            raise not_found("design")
        row = await records.set_design_status(
            conn, design_id, "uploaded", expected=("awaiting_upload", "failed")
        )
        if row is None:
            raise conflict("design upload already completed")
        await emit_audit(
            conn,
            AuditEvent(
                action="design.upload_complete",
                object_type="design",
                object_id=str(design_id),
                source_ip=_source_ip(request),
            ),
            ctx,
        )
    await svc.ingest_queue.send(Message.create(DESIGN_UPLOADED, ctx, {"design_id": str(design_id)}))
    return _design(row)


@router.get("/designs/{design_id}", response_model=Design, tags=["designs"])
async def get_design(design_id: uuid.UUID, ctx: Ctx, svc: Svc) -> Design:
    require(*CAN_READ)(ctx)
    async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
        row = await records.get_design(conn, design_id)
    if row is None:
        raise not_found("design")
    return _design(row)


# ------------------------------------------------------------------ runs
@router.post("/runs", status_code=202, response_model=Run, tags=["runs"])
async def create_run(
    body: RunIn,
    request: Request,
    response: Response,
    ctx: Ctx,
    svc: Svc,
    idempotency_key: Annotated[str, Header(min_length=8, max_length=128)],
) -> Run:
    require(*CAN_WRITE)(ctx)
    try:
        spec = svc.catalog.get(body.model_id, allow_local=svc.allow_local_models)
    except ModelNotAllowedError as exc:
        raise ProblemError(
            422, "Unprocessable Content", str(exc), slug="model-not-allowed"
        ) from exc
    async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
        design = await records.get_design(conn, body.design_id)
        if design is None:
            raise not_found("design")
        if design["status"] != "parsed":
            raise conflict(f"design is {design['status']}, not parsed")
        row, created = await records.insert_run(
            conn,
            tenant_id=ctx.tenant_id,
            design_id=body.design_id,
            variant=body.variant,
            model_id=spec.id,
            idempotency_key=idempotency_key,
            requirements=body.requirements.model_dump(mode="json"),
            budget=body.budget,
            created_by=ctx.actor_id,
        )
        if created:
            await emit_audit(
                conn,
                AuditEvent(
                    action="run.create",
                    object_type="run",
                    object_id=str(row["id"]),
                    after={
                        "variant": body.variant,
                        "model_id": spec.id,
                        "design_id": str(body.design_id),
                    },
                    source_ip=_source_ip(request),
                ),
                ctx,
            )
    if created:
        await svc.runs_queue.send(
            Message.create(
                RUN_REQUESTED,
                ctx,
                {
                    "run_id": str(row["id"]),
                    "variant": body.variant,
                    "model_id": spec.id,
                    "design_key": design["parsed_key"],
                    "requirements": body.requirements.model_dump(mode="json"),
                    "budget": body.budget,
                },
            )
        )
    else:
        response.status_code = 200
    return Run.model_validate(row)


@router.get("/runs", response_model=Page[Run], tags=["runs"])
async def list_runs(
    ctx: Ctx, svc: Svc, limit: Annotated[int, Query(ge=1, le=100)] = 20, cursor: str | None = None
) -> Page[Run]:
    require(*CAN_READ)(ctx)
    try:
        async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
            rows, nxt = await records.list_runs(conn, limit, cursor)
    except ValueError as exc:
        raise ProblemError(400, "Bad Request", str(exc), slug="bad-cursor") from exc
    return Page[Run](items=[Run.model_validate(r) for r in rows], next_cursor=nxt)


async def _run_row(svc: ApiServices, ctx: TenantContext, run_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
        row = await records.get_run(conn, run_id)
    if row is None:
        raise not_found("run")
    return row


@router.get("/runs/{run_id}", response_model=Run, tags=["runs"])
async def get_run(run_id: uuid.UUID, ctx: Ctx, svc: Svc) -> Run:
    require(*CAN_READ)(ctx)
    return Run.model_validate(await _run_row(svc, ctx, run_id))


async def _artefact(svc: ApiServices, ctx: TenantContext, key: str | None, what: str) -> Response:
    if not key:
        raise conflict(f"{what} is not available yet")
    with tenant_scope(ctx):
        data = await svc.store.get(key)
    return Response(content=data, media_type="application/json")


@router.get(
    "/runs/{run_id}/bom", tags=["runs"], responses={200: {"content": {"application/json": {}}}}
)
async def get_run_bom(run_id: uuid.UUID, ctx: Ctx, svc: Svc) -> Response:
    """The ``BomVersion`` JSON (lines with per-field provenance and findings)."""
    require(*CAN_READ)(ctx)
    row = await _run_row(svc, ctx, run_id)
    return await _artefact(svc, ctx, row["bom_key"], "BOM")


@router.get(
    "/runs/{run_id}/trace", tags=["runs"], responses={200: {"content": {"application/json": {}}}}
)
async def get_run_trace(run_id: uuid.UUID, ctx: Ctx, svc: Svc) -> Response:
    """Trace of agent/rule steps, usage and run configuration."""
    require(*CAN_READ)(ctx)
    row = await _run_row(svc, ctx, run_id)
    return await _artefact(svc, ctx, row["result_key"], "trace")


@router.get(
    "/runs/{run_id}/events", tags=["runs"], responses={200: {"content": {"text/event-stream": {}}}}
)
async def run_events(run_id: uuid.UUID, ctx: Ctx, svc: Svc) -> StreamingResponse:
    """Server-sent events: one ``status`` event per change until the run finishes."""
    require(*CAN_READ)(ctx)
    await _run_row(svc, ctx, run_id)

    async def stream() -> AsyncIterator[str]:
        last = None
        while True:
            row = await _run_row(svc, ctx, run_id)
            if row["status"] != last:
                last = row["status"]
                payload = Run.model_validate(row).model_dump(mode="json")
                yield f"event: status\ndata: {json.dumps(payload)}\n\n"
            if last in {"completed", "failed"}:
                return
            await asyncio.sleep(svc.sse_poll_seconds)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


# ------------------------------------------------------------------ audit
@router.get("/audit/events", response_model=Page[AuditEntry], tags=["audit"])
async def audit_events(
    ctx: Ctx,
    svc: Svc,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_seq: int | None = None,
) -> Page[AuditEntry]:
    require(*CAN_AUDIT)(ctx)
    async with tenant_transaction(svc.engine, ctx.tenant_id) as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        """SELECT seq, occurred_at, actor_type, actor_id, action, object_type,
                              object_id, hash
                       FROM audit.events WHERE (CAST(:before AS bigint) IS NULL OR seq < :before)
                       ORDER BY seq DESC LIMIT :lim"""
                    ),
                    {"before": before_seq, "lim": limit + 1},
                )
            )
            .mappings()
            .all()
        )
    items = [AuditEntry.model_validate(dict(r)) for r in rows[:limit]]
    nxt = str(items[-1].seq) if len(rows) > limit else None
    return Page[AuditEntry](items=items, next_cursor=nxt)
