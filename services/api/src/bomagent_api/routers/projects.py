"""Projects and design-file uploads."""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, UploadFile
from sqlalchemy import text

from bomagent_api import idempotency
from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.pagination import clamp, encode_cursor, page_clause
from bomagent_api.schemas import FileInfo, Page, Project, ProjectCreate, problem_responses
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import Message
from bomagent_common.problems import ProblemError
from bomagent_common.storage import tenant_key

router = APIRouter(
    prefix="/v1/projects",
    tags=["projects"],
    responses=problem_responses(400, 401, 403, 404, 409, 413, 422),
)
MAX_UPLOAD = 64 * 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-]")
PROJECT_COLS = "id, name, description, created_by, created_at"


async def get_project(conn: Any, project_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(
                f"SELECT {PROJECT_COLS} FROM projects.projects"  # noqa: S608
                " WHERE id = :i"
            ),
            {"i": project_id},
        )
    ).first()
    if row is None:  # other tenants' projects are invisible (RLS) -> 404, never 403
        raise ProblemError(404, "Not Found", "project not found", slug="not-found")
    return dict(row._mapping)


@router.get("", summary="List projects")
async def list_projects(
    request: Request, ctx: OrgContext, cursor: str | None = None, limit: int = 25
) -> Page[Project]:
    require(ctx, "project.read")
    params: dict[str, Any] = {"lim": clamp(limit) + 1}
    sql = (
        f"SELECT {PROJECT_COLS} FROM projects.projects WHERE true"  # noqa: S608
        f"{page_clause(cursor, params)} ORDER BY created_at DESC, id DESC LIMIT :lim"
    )
    async with tenant_transaction(request.app.state.engine) as conn:
        rows = [dict(r._mapping) for r in await conn.execute(text(sql), params)]
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more else None
    return Page[Project](items=[Project(**r) for r in rows], next_cursor=nxt)


@router.post("", status_code=201, summary="Create a project")
async def create_project(
    request: Request,
    ctx: OrgContext,
    body: ProjectCreate,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Project:
    require(ctx, "project.create")
    payload = body.model_dump()
    async with tenant_transaction(request.app.state.engine) as conn:
        stored = await idempotency.replay(conn, idempotency_key, payload)
        if stored is not None:
            return Project(**stored)
        pid = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO projects.projects (id, tenant_id, name, description,"
                " created_by) VALUES (:i, app.current_tenant_id(), :n, :d, :u)"
            ),
            {"i": pid, "n": body.name, "d": body.description, "u": ctx.actor_id},
        )
        project = Project(**await get_project(conn, pid))
        await emit_audit(
            conn,
            AuditEvent(
                action="project.created", object_type="project", object_id=str(pid), after=payload
            ),
        )
        await idempotency.store(
            conn, idempotency_key, payload, 201, project.model_dump(mode="json")
        )
    return project


@router.get("/{project_id}", summary="Get a project")
async def read_project(request: Request, ctx: OrgContext, project_id: uuid.UUID) -> Project:
    require(ctx, "project.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        return Project(**await get_project(conn, project_id))


FILE_COLS = "id, name, size_bytes, sha256, status, detected_format, summary, created_at"


@router.get("/{project_id}/files", summary="List design files of a project")
async def list_files(request: Request, ctx: OrgContext, project_id: uuid.UUID) -> list[FileInfo]:
    require(ctx, "project.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        await get_project(conn, project_id)
        rows = await conn.execute(
            text(
                f"SELECT {FILE_COLS} FROM projects.files"  # noqa: S608
                " WHERE project_id = :p ORDER BY name"
            ),
            {"p": project_id},
        )
        return [FileInfo(**dict(r._mapping)) for r in rows]


@router.post("/{project_id}/files", status_code=201, summary="Upload a design file")
async def upload_file(
    request: Request, ctx: OrgContext, project_id: uuid.UUID, file: UploadFile
) -> FileInfo:
    """Stores the file under the tenant prefix and queues it for the sandboxed
    ingest-worker (parsing never happens in the API process - ADR-0009)."""
    require(ctx, "file.upload")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise ProblemError(
            413, "Payload Too Large", "file larger than 64 MB", slug="file-too-large"
        )
    name = _SAFE_NAME.sub("_", (file.filename or "upload").rsplit("/", 1)[-1])[:200] or "upload"
    async with tenant_transaction(request.app.state.engine) as conn:
        await get_project(conn, project_id)
        fid = uuid.uuid4()
        key = tenant_key(ctx.tenant_id, "projects", str(project_id), str(fid), name)
        await request.app.state.store.put(
            key, data, file.content_type or "application/octet-stream"
        )
        await conn.execute(
            text(
                "INSERT INTO projects.files (id, tenant_id, project_id, name,"
                " object_key, sha256, size_bytes, created_by) VALUES (:i,"
                " app.current_tenant_id(), :p, :n, :k, :h, :s, :u)"
                " ON CONFLICT (tenant_id, project_id, name) DO UPDATE SET object_key ="
                " EXCLUDED.object_key, sha256 = EXCLUDED.sha256, size_bytes ="
                " EXCLUDED.size_bytes, status = 'uploaded', summary = '{}'"
            ),
            {
                "i": fid,
                "p": project_id,
                "n": name,
                "k": key,
                "h": hashlib.sha256(data).hexdigest(),
                "s": len(data),
                "u": ctx.actor_id,
            },
        )
        row = (
            await conn.execute(
                text(
                    f"SELECT {FILE_COLS} FROM projects.files"  # noqa: S608
                    " WHERE project_id = :p AND name = :n"
                ),
                {"p": project_id, "n": name},
            )
        ).one()
        info = FileInfo(**dict(row._mapping))
        await emit_audit(
            conn,
            AuditEvent(
                action="file.uploaded",
                object_type="file",
                object_id=str(info.id),
                after={"name": name, "sha256": info.sha256, "size": len(data)},
            ),
        )
    await request.app.state.queues["ingest"].send(
        Message.create(
            "file.uploaded", ctx, {"project_id": str(project_id), "file_id": str(info.id)}
        )
    )
    return info
