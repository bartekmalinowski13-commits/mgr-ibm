"""Projects and design-file uploads."""

from __future__ import annotations

import contextlib
import hashlib
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, Response, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_api import idempotency
from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.pagination import clamp, encode_cursor, page_clause
from bomagent_api.plans import check_new_project, check_storage, plan_of
from bomagent_api.schemas import (
    FileInfo,
    Page,
    Project,
    ProjectCreate,
    ProjectUpdate,
    problem_responses,
)
from bomagent_cad.sandbox import MAX_PROJECT_BYTES, MAX_PROJECT_FILES
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message
from bomagent_common.metering import record_usage
from bomagent_common.outbox import deliver, enqueue
from bomagent_common.problems import ProblemError
from bomagent_common.storage import key_belongs_to, tenant_key

router = APIRouter(
    prefix="/v1/projects",
    tags=["projects"],
    responses=problem_responses(400, 401, 403, 404, 409, 413, 422, 429),
)
log = get_logger(__name__)
MAX_UPLOAD = 64 * 1024 * 1024


async def check_project_size(
    conn: AsyncConnection, project_id: uuid.UUID, new_bytes: int, previous: Any
) -> None:
    """Workers hold a whole project in memory to parse it: bound files and bytes per project
    (same limits the workers enforce, ``bomagent_cad.sandbox``)."""
    count, total = (
        await conn.execute(
            text(
                "SELECT count(*), COALESCE(sum(size_bytes), 0) FROM projects.files"
                " WHERE project_id = :p"
            ),
            {"p": project_id},
        )
    ).one()
    if previous is None:
        count += 1
    total = int(total) - (previous.size_bytes if previous is not None else 0) + new_bytes
    if count > MAX_PROJECT_FILES or total > MAX_PROJECT_BYTES:
        raise ProblemError(
            413,
            "Content Too Large",
            f"a project holds at most {MAX_PROJECT_FILES} files and"
            f" {MAX_PROJECT_BYTES // (1024 * 1024)} MiB",
            slug="project-too-large",
        )


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-]")
PROJECT_COLS = (
    "id, name, description, created_by, created_at, (sample_key IS NOT NULL) AS is_sample"
)


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
        stored = await idempotency.replay(
            conn, idempotency_key, payload, route=idempotency.route_of(request)
        )
        if stored is not None:
            return Project(**stored)
        await check_new_project(conn)
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
            conn,
            idempotency_key,
            payload,
            201,
            project.model_dump(mode="json"),
            route=idempotency.route_of(request),
        )
    return project


@router.get("/{project_id}", summary="Get a project")
async def read_project(request: Request, ctx: OrgContext, project_id: uuid.UUID) -> Project:
    require(ctx, "project.read")
    async with tenant_transaction(request.app.state.engine) as conn:
        return Project(**await get_project(conn, project_id))


@router.patch("/{project_id}", summary="Rename a project or change its description")
async def update_project(
    request: Request, ctx: OrgContext, project_id: uuid.UUID, body: ProjectUpdate
) -> Project:
    """Sample projects are platform-owned and read-only; everything else can be renamed."""
    require(ctx, "project.create")
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise ProblemError(422, "Unprocessable Entity", "nothing to change", slug="empty-patch")
    async with tenant_transaction(request.app.state.engine) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT name, description, sample_key FROM projects.projects"
                    " WHERE id = :i FOR UPDATE"
                ),
                {"i": project_id},
            )
        ).first()
        if row is None:
            raise ProblemError(404, "Not Found", "project not found", slug="not-found")
        if row.sample_key is not None:
            raise ProblemError(
                409,
                "Conflict",
                "sample projects are read-only; create your own project",
                slug="sample-read-only",
            )
        await conn.execute(
            text(
                "UPDATE projects.projects SET name = COALESCE(:n, name),"
                " description = COALESCE(:d, description) WHERE id = :i"
            ),
            {"n": changes.get("name"), "d": changes.get("description"), "i": project_id},
        )
        before = {"name": row.name, "description": row.description}
        project = Project(**await get_project(conn, project_id))
        await emit_audit(
            conn,
            AuditEvent(
                action="project.updated",
                object_type="project",
                object_id=str(project_id),
                before={k: before[k] for k in changes},
                after=changes,
            ),
        )
    return project


@router.delete("/{project_id}", status_code=204, summary="Delete a project")
async def delete_project(request: Request, ctx: OrgContext, project_id: uuid.UUID) -> Response:
    """Deletes a project (own or sample). Files, runs and BOM versions go with the project
    (cascade); the stored objects are removed after the commit, under the tenant prefix only.
    Refused while a run of the project is queued or running (``file-in-use``)."""
    require(ctx, "project.delete")
    store = request.app.state.store
    async with tenant_transaction(request.app.state.engine) as conn:
        row = (
            await conn.execute(
                text("SELECT sample_key, name FROM projects.projects WHERE id = :i FOR UPDATE"),
                {"i": project_id},
            )
        ).first()
        if row is None:
            raise ProblemError(404, "Not Found", "project not found", slug="not-found")
        await refuse_if_run_active(conn, project_id, "deleting it")
        keys = list(
            (
                await conn.execute(
                    text("SELECT object_key FROM projects.files WHERE project_id = :p"),
                    {"p": project_id},
                )
            ).scalars()
        )
        run_ids = list(
            (
                await conn.execute(
                    text("SELECT id FROM runs.runs WHERE project_id = :p"), {"p": project_id}
                )
            ).scalars()
        )
        bom_versions = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM bom.versions WHERE run_id IN"
                    " (SELECT id FROM runs.runs WHERE project_id = :p)"
                ),
                {"p": project_id},
            )
        ).scalar()
        # queued ingest work of the project goes with it
        await conn.execute(
            text(
                "DELETE FROM app.outbox WHERE sent_at IS NULL"
                " AND message->'payload'->>'project_id' = :p"
            ),
            {"p": str(project_id)},
        )
        await conn.execute(text("DELETE FROM projects.projects WHERE id = :i"), {"i": project_id})
        await emit_audit(
            conn,
            AuditEvent(
                action="project.deleted",
                object_type="project",
                object_id=str(project_id),
                before={
                    "name": row.name,
                    "sample": row.sample_key,
                    "files": len(keys),
                    "runs": len(run_ids),
                    "bom_versions": int(bom_versions or 0),
                },
            ),
        )
    for run_id in run_ids:
        for artifact in ("bom.json", "trace.json"):
            keys.append(tenant_key(ctx.tenant_id, "runs", str(run_id), artifact))
    await delete_objects(store, ctx.tenant_id, keys, project_id=str(project_id))
    return Response(status_code=204)


async def delete_objects(store: Any, tenant_id: uuid.UUID, keys: list[str], **context: str) -> None:
    """Remove stored objects after the rows are gone: only keys under the tenant's own prefix
    are touched, and a failed cleanup must not turn a retry into a 404."""
    for key in keys:
        if not key_belongs_to(tenant_id, key):
            log.error("object_cleanup_refused_foreign_key", key=key, **context)
            continue
        try:
            await store.delete(key)
        except Exception:
            log.warning("object_cleanup_failed", key=key, **context)


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


@router.delete("/{project_id}/files/{file_id}", status_code=204, summary="Delete a design file")
async def delete_file(
    request: Request, ctx: OrgContext, project_id: uuid.UUID, file_id: uuid.UUID
) -> Response:
    """Removes the file and its stored object. Refused while a run of the project is queued or
    running (``file-in-use``): the run holds the object keys. Sample projects are read-only."""
    require(ctx, "file.upload")
    async with tenant_transaction(request.app.state.engine) as conn:
        refuse_sample_upload(await get_project(conn, project_id))
        row = (
            await conn.execute(
                text(
                    "SELECT name, object_key, sha256, size_bytes FROM projects.files"
                    " WHERE id = :f AND project_id = :p FOR UPDATE"
                ),
                {"f": file_id, "p": project_id},
            )
        ).first()
        if row is None:
            raise ProblemError(404, "Not Found", "file not found", slug="not-found")
        await refuse_if_run_active(conn, project_id, "deleting a file")
        await conn.execute(text("DELETE FROM projects.files WHERE id = :f"), {"f": file_id})
        # a queued ingest of this file has nothing left to parse
        await conn.execute(
            text(
                "DELETE FROM app.outbox WHERE sent_at IS NULL"
                " AND message->'payload'->>'file_id' = :f"
            ),
            {"f": str(file_id)},
        )
        await emit_audit(
            conn,
            AuditEvent(
                action="file.deleted",
                object_type="file",
                object_id=str(file_id),
                before={"name": row.name, "sha256": row.sha256, "size": row.size_bytes},
            ),
        )
    await delete_objects(
        request.app.state.store, ctx.tenant_id, [row.object_key], file_id=str(file_id)
    )
    return Response(status_code=204)


UPLOAD_CHUNK = 1024 * 1024


async def measure_upload(file: UploadFile, *, limit: int) -> tuple[int, str]:
    """Size and SHA-256 of the upload, read in chunks (the multipart body is already spooled
    to disk by Starlette); refuses files over ``limit`` as soon as the limit is crossed. The
    file is rewound so the object store can stream it."""
    digest = hashlib.sha256()
    size = 0
    while chunk := await file.read(UPLOAD_CHUNK):
        size += len(chunk)
        if size > limit:
            raise ProblemError(
                413, "Payload Too Large", "file larger than 64 MB", slug="file-too-large"
            )
        digest.update(chunk)
    await file.seek(0)
    return size, digest.hexdigest()


@router.post("/{project_id}/files", status_code=201, summary="Upload a design file")
async def upload_file(
    request: Request, ctx: OrgContext, project_id: uuid.UUID, file: UploadFile
) -> FileInfo:
    """Stores the file under the tenant prefix and queues it for the sandboxed
    ingest-worker (parsing never happens in the API process - ADR-0009)."""
    require(ctx, "file.upload")
    size, sha256 = await measure_upload(file, limit=MAX_UPLOAD)
    name = _SAFE_NAME.sub("_", (file.filename or "upload").rsplit("/", 1)[-1])[:200] or "upload"
    store = request.app.state.store
    fid = uuid.uuid4()
    key = tenant_key(ctx.tenant_id, "projects", str(project_id), str(fid), name)
    try:
        async with tenant_transaction(request.app.state.engine) as conn:
            refuse_sample_upload(await get_project(conn, project_id))
            # the tenant lock (taken by check_storage) serialises uploads of an organisation,
            # so two uploads of one name never both see "no previous file"
            await plan_of(conn, lock=True)
            previous = (
                await conn.execute(
                    text(
                        "SELECT object_key, sha256, size_bytes FROM projects.files"
                        " WHERE project_id = :p AND name = :n FOR UPDATE"
                    ),
                    {"p": project_id, "n": name},
                )
            ).first()
            if previous is not None:
                await refuse_if_run_active(conn, project_id)
            await check_storage(conn, size, previous.size_bytes if previous else 0)
            await check_project_size(conn, project_id, size, previous)
            # the client's content type is never stored or served back
            await store.put_file(key, file.file, "application/octet-stream")
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
                    "h": sha256,
                    "s": size,
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
                    before=(
                        {"sha256": previous.sha256, "size": previous.size_bytes}
                        if previous
                        else None
                    ),
                    after={"name": name, "sha256": info.sha256, "size": size},
                ),
            )
            await record_usage(conn, files_uploaded=1, bytes_uploaded=size)
            outbox_id = await enqueue(
                conn,
                "ingest",
                Message.create(
                    "file.uploaded", ctx, {"project_id": str(project_id), "file_id": str(info.id)}
                ),
            )
    except BaseException:
        # the row was not committed: drop the new object (best effort - a failing cleanup
        # must not mask the original error)
        with contextlib.suppress(Exception):
            await store.delete(key)
        raise
    if previous is not None and previous.object_key != key:
        await store.delete(previous.object_key)  # replaced: keep no orphaned copies
    await deliver_now(request, ctx.tenant_id, outbox_id)
    return info


def refuse_sample_upload(project: dict[str, Any]) -> None:
    if project["is_sample"]:
        raise ProblemError(
            409,
            "Conflict",
            "sample projects are read-only; create your own project to upload files",
            slug="sample-read-only",
        )


async def refuse_if_run_active(
    conn: Any, project_id: uuid.UUID, action: str = "replacing a file"
) -> None:
    """A queued or running run holds the object keys of the project's files."""
    active = (
        await conn.execute(
            text(
                "SELECT 1 FROM runs.runs WHERE project_id = :p"
                " AND status IN ('queued', 'running') LIMIT 1"
            ),
            {"p": project_id},
        )
    ).first()
    if active is not None:
        raise ProblemError(
            409,
            "Conflict",
            f"a run of this project is queued or running; wait until it finishes before {action}",
            slug="file-in-use",
        )


async def deliver_now(request: Request, tenant_id: uuid.UUID, outbox_id: uuid.UUID) -> None:
    """Send a committed outbox message right away; on failure the relay retries it."""
    try:
        await deliver(
            request.app.state.engine, tenant_id, request.app.state.queues, ids=[outbox_id]
        )
    except Exception:
        log.warning("outbox_deliver_deferred", outbox_id=str(outbox_id))
