"""Projects and design-file uploads (HTTP only; the use cases are in ``services.projects``)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response, UploadFile

from bomagent_api import idempotency
from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.schemas import (
    FileInfo,
    Page,
    Project,
    ProjectCreate,
    ProjectUpdate,
    problem_responses,
)
from bomagent_api.services import projects as service
from bomagent_cad.sandbox import MAX_PROJECT_BYTES, MAX_PROJECT_FILES
from bomagent_common.problems import ProblemError

router = APIRouter(
    prefix="/v1/projects",
    tags=["projects"],
    responses=problem_responses(400, 401, 403, 404, 409, 413, 422, 429),
)
MAX_UPLOAD = 64 * 1024 * 1024
UPLOAD_CHUNK = 1024 * 1024


@router.get("", summary="List projects")
async def list_projects(
    request: Request, ctx: OrgContext, cursor: str | None = None, limit: int = 25
) -> Page[Project]:
    require(ctx, "project.read")
    return await service.list_projects(request.app.state.engine, cursor=cursor, limit=limit)


@router.post("", status_code=201, summary="Create a project")
async def create_project(
    request: Request,
    ctx: OrgContext,
    body: ProjectCreate,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Project:
    require(ctx, "project.create")
    return await service.create_project(
        request.app.state.engine,
        ctx,
        body,
        idempotency_key=idempotency_key,
        route=idempotency.route_of(request),
    )


@router.get("/{project_id}", summary="Get a project")
async def read_project(request: Request, ctx: OrgContext, project_id: uuid.UUID) -> Project:
    require(ctx, "project.read")
    return await service.read_project(request.app.state.engine, project_id)


@router.patch("/{project_id}", summary="Rename a project or change its description")
async def update_project(
    request: Request, ctx: OrgContext, project_id: uuid.UUID, body: ProjectUpdate
) -> Project:
    """Sample projects are platform-owned and read-only; everything else can be renamed."""
    require(ctx, "project.create")
    return await service.update_project(request.app.state.engine, project_id, body)


@router.delete("/{project_id}", status_code=204, summary="Delete a project")
async def delete_project(request: Request, ctx: OrgContext, project_id: uuid.UUID) -> Response:
    """Deletes a project (own or sample). Files, runs and BOM versions go with the project
    (cascade); the stored objects are removed after the commit, under the tenant prefix only.
    Refused while a run of the project is queued or running (``file-in-use``)."""
    require(ctx, "project.delete")
    await service.delete_project(request.app.state.engine, request.app.state.store, ctx, project_id)
    return Response(status_code=204)


@router.get("/{project_id}/files", summary="List design files of a project")
async def list_files(request: Request, ctx: OrgContext, project_id: uuid.UUID) -> list[FileInfo]:
    require(ctx, "project.read")
    return await service.list_files(request.app.state.engine, project_id)


@router.delete("/{project_id}/files/{file_id}", status_code=204, summary="Delete a design file")
async def delete_file(
    request: Request, ctx: OrgContext, project_id: uuid.UUID, file_id: uuid.UUID
) -> Response:
    """Removes the file and its stored object. Refused while a run of the project is queued or
    running (``file-in-use``): the run holds the object keys. Sample projects are read-only."""
    require(ctx, "file.upload")
    await service.delete_file(
        request.app.state.engine, request.app.state.store, ctx, project_id, file_id
    )
    return Response(status_code=204)


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
    # the per-project limits are read here, at call time, and handed to the service
    return await service.upload_file(
        request.app.state.engine,
        request.app.state.store,
        request.app.state.queues,
        ctx,
        project_id,
        filename=file.filename,
        content=file.file,
        size=size,
        sha256=sha256,
        max_project_files=MAX_PROJECT_FILES,
        max_project_bytes=MAX_PROJECT_BYTES,
    )
