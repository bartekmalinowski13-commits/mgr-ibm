"""Projects and design-file uploads: transactions, quota, audit and outbox (ARCH-04)."""

from __future__ import annotations

import contextlib
import re
import uuid
from collections.abc import Mapping
from typing import Any, BinaryIO

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bomagent_api import idempotency
from bomagent_api.pagination import clamp, encode_cursor, page_filter
from bomagent_api.plans import check_new_project, check_storage, plan_of
from bomagent_api.repositories import projects as repo
from bomagent_api.repositories import runs as runs_repo
from bomagent_api.repositories.tables import projects as projects_table
from bomagent_api.schemas import FileInfo, Page, Project, ProjectCreate, ProjectUpdate
from bomagent_api.services.outbox import deliver_now
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message, Queue
from bomagent_common.metering import record_usage
from bomagent_common.outbox import enqueue
from bomagent_common.problems import ProblemError
from bomagent_common.storage import ObjectStore, key_belongs_to, tenant_key
from bomagent_common.tenancy import TenantContext

log = get_logger(__name__)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-]")


def safe_filename(filename: str | None) -> str:
    """Last path segment of a client file name with anything but ``[A-Za-z0-9._-]`` replaced."""
    return _SAFE_NAME.sub("_", (filename or "upload").rsplit("/", 1)[-1])[:200] or "upload"


def _not_found() -> ProblemError:
    return ProblemError(404, "Not Found", "project not found", slug="not-found")


async def get_project(conn: AsyncConnection, project_id: uuid.UUID) -> dict[str, Any]:
    row = await repo.get(conn, project_id)
    if row is None:  # other tenants' projects are invisible (RLS) -> 404, never 403
        raise _not_found()
    return row


def refuse_sample_upload(project: dict[str, Any]) -> None:
    if project["is_sample"]:
        raise ProblemError(
            409,
            "Conflict",
            "sample projects are read-only; create your own project to upload files",
            slug="sample-read-only",
        )


async def refuse_if_run_active(
    conn: AsyncConnection, project_id: uuid.UUID, action: str = "replacing a file"
) -> None:
    """A queued or running run holds the object keys of the project's files."""
    if await runs_repo.has_active_run(conn, project_id):
        raise ProblemError(
            409,
            "Conflict",
            f"a run of this project is queued or running; wait until it finishes before {action}",
            slug="file-in-use",
        )


async def check_project_size(
    conn: AsyncConnection,
    project_id: uuid.UUID,
    new_bytes: int,
    previous: Any,
    *,
    max_files: int,
    max_bytes: int,
) -> None:
    """Workers hold a whole project in memory to parse it: bound files and bytes per project
    (the limits are the ones the workers enforce, ``bomagent_cad.sandbox``)."""
    count, total = await repo.file_totals(conn, project_id)
    if previous is None:
        count += 1
    total = total - (previous.size_bytes if previous is not None else 0) + new_bytes
    if count > max_files or total > max_bytes:
        raise ProblemError(
            413,
            "Content Too Large",
            f"a project holds at most {max_files} files and {max_bytes // (1024 * 1024)} MiB",
            slug="project-too-large",
        )


async def delete_objects(
    store: ObjectStore, tenant_id: uuid.UUID, keys: list[str], **context: str
) -> None:
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


# --------------------------------------------------------------------------- projects
async def list_projects(engine: AsyncEngine, *, cursor: str | None, limit: int) -> Page[Project]:
    after = page_filter(cursor, projects_table.c.created_at, projects_table.c.id)
    async with tenant_transaction(engine) as conn:
        rows = await repo.list_page(conn, after=after, limit=clamp(limit) + 1)
    more = len(rows) > clamp(limit)
    rows = rows[: clamp(limit)]
    nxt = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if more else None
    return Page[Project](items=[Project(**r) for r in rows], next_cursor=nxt)


async def create_project(
    engine: AsyncEngine,
    ctx: TenantContext,
    body: ProjectCreate,
    *,
    idempotency_key: str | None,
    route: str,
) -> Project:
    payload = body.model_dump()
    async with tenant_transaction(engine) as conn:
        stored = await idempotency.replay(conn, idempotency_key, payload, route=route)
        if stored is not None:
            return Project(**stored)
        await check_new_project(conn)
        pid = uuid.uuid4()
        await repo.insert_project(
            conn,
            project_id=pid,
            name=body.name,
            description=body.description,
            created_by=ctx.actor_id,
        )
        project = Project(**await get_project(conn, pid))
        await emit_audit(
            conn,
            AuditEvent(
                action="project.created", object_type="project", object_id=str(pid), after=payload
            ),
        )
        await idempotency.store(
            conn, idempotency_key, payload, 201, project.model_dump(mode="json"), route=route
        )
    return project


async def read_project(engine: AsyncEngine, project_id: uuid.UUID) -> Project:
    async with tenant_transaction(engine) as conn:
        return Project(**await get_project(conn, project_id))


async def update_project(
    engine: AsyncEngine, project_id: uuid.UUID, body: ProjectUpdate
) -> Project:
    """Sample projects are platform-owned and read-only; everything else can be renamed."""
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise ProblemError(422, "Unprocessable Entity", "nothing to change", slug="empty-patch")
    async with tenant_transaction(engine) as conn:
        row = await repo.lock(conn, project_id)
        if row is None:
            raise _not_found()
        if row.sample_key is not None:
            raise ProblemError(
                409,
                "Conflict",
                "sample projects are read-only; create your own project",
                slug="sample-read-only",
            )
        await repo.update_project(
            conn, project_id, name=changes.get("name"), description=changes.get("description")
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


async def delete_project(
    engine: AsyncEngine, store: ObjectStore, ctx: TenantContext, project_id: uuid.UUID
) -> None:
    """Deletes a project (own or sample). Files, runs and BOM versions go with the project
    (cascade); the stored objects are removed after the commit, under the tenant prefix only.
    Refused while a run of the project is queued or running (``file-in-use``)."""
    async with tenant_transaction(engine) as conn:
        row = await repo.lock(conn, project_id)
        if row is None:
            raise _not_found()
        await refuse_if_run_active(conn, project_id, "deleting it")
        keys = await repo.object_keys(conn, project_id)
        run_ids = await repo.run_ids(conn, project_id)
        bom_versions = await repo.bom_version_count(conn, project_id)
        await repo.delete_queued_outbox_of_project(conn, project_id)
        await repo.delete_project(conn, project_id)
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
                    "bom_versions": bom_versions,
                },
            ),
        )
    for run_id in run_ids:
        for artifact in ("bom.json", "trace.json"):
            keys.append(tenant_key(ctx.tenant_id, "runs", str(run_id), artifact))
    await delete_objects(store, ctx.tenant_id, keys, project_id=str(project_id))


# ------------------------------------------------------------------------------ files
async def list_files(engine: AsyncEngine, project_id: uuid.UUID) -> list[FileInfo]:
    async with tenant_transaction(engine) as conn:
        await get_project(conn, project_id)
        return [FileInfo(**r) for r in await repo.list_files(conn, project_id)]


async def delete_file(
    engine: AsyncEngine,
    store: ObjectStore,
    ctx: TenantContext,
    project_id: uuid.UUID,
    file_id: uuid.UUID,
) -> None:
    """Removes the file and its stored object. Refused while a run of the project is queued or
    running (``file-in-use``): the run holds the object keys. Sample projects are read-only."""
    async with tenant_transaction(engine) as conn:
        refuse_sample_upload(await get_project(conn, project_id))
        row = await repo.lock_file(conn, project_id, file_id)
        if row is None:
            raise ProblemError(404, "Not Found", "file not found", slug="not-found")
        await refuse_if_run_active(conn, project_id, "deleting a file")
        await repo.delete_file(conn, file_id)
        await repo.delete_queued_outbox_of_file(conn, file_id)
        await emit_audit(
            conn,
            AuditEvent(
                action="file.deleted",
                object_type="file",
                object_id=str(file_id),
                before={"name": row.name, "sha256": row.sha256, "size": row.size_bytes},
            ),
        )
    await delete_objects(store, ctx.tenant_id, [row.object_key], file_id=str(file_id))


async def upload_file(
    engine: AsyncEngine,
    store: ObjectStore,
    queues: Mapping[str, Queue],
    ctx: TenantContext,
    project_id: uuid.UUID,
    *,
    filename: str | None,
    content: BinaryIO,
    size: int,
    sha256: str,
    max_project_files: int,
    max_project_bytes: int,
) -> FileInfo:
    """Stores the file under the tenant prefix and queues it for the sandboxed
    ingest-worker (parsing never happens in the API process - ADR-0009)."""
    name = safe_filename(filename)
    fid = uuid.uuid4()
    key = tenant_key(ctx.tenant_id, "projects", str(project_id), str(fid), name)
    try:
        async with tenant_transaction(engine) as conn:
            refuse_sample_upload(await get_project(conn, project_id))
            # the tenant lock (taken by check_storage) serialises uploads of an organisation,
            # so two uploads of one name never both see "no previous file"
            await plan_of(conn, lock=True)
            previous = await repo.lock_file_by_name(conn, project_id, name)
            if previous is not None:
                await refuse_if_run_active(conn, project_id)
            await check_storage(conn, size, previous.size_bytes if previous else 0)
            await check_project_size(
                conn,
                project_id,
                size,
                previous,
                max_files=max_project_files,
                max_bytes=max_project_bytes,
            )
            # the client's content type is never stored or served back
            await store.put_file(key, content, "application/octet-stream")
            await repo.upsert_file(
                conn,
                file_id=fid,
                project_id=project_id,
                name=name,
                object_key=key,
                sha256=sha256,
                size_bytes=size,
                created_by=ctx.actor_id,
            )
            info = FileInfo(**await repo.get_file_by_name(conn, project_id, name))
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
    await deliver_now(engine, queues, ctx.tenant_id, outbox_id)
    return info
