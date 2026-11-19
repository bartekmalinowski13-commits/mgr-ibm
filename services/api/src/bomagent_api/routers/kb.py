"""Knowledge base of the organisation (ADR-0008) and a read-only view of the global corpus.

Uploads are stored under the tenant prefix and announced to the ``kb-indexer`` through
the outbox; extraction and chunking never run in the API process. Document text is
untrusted: it is indexed with prompt-injection flagging and never shown as instructions.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Form, Request, Response, UploadFile

from bomagent_api.auth import OrgContext
from bomagent_api.authz import require
from bomagent_api.schemas import KbDocument, Page, problem_responses
from bomagent_api.services import kb as service
from bomagent_common.problems import ProblemError

router = APIRouter(
    prefix="/v1/kb",
    tags=["knowledge base"],
    responses=problem_responses(400, 401, 403, 413, 415, 422, 429),
)
MAX_DOCUMENT = 32 * 1024 * 1024


@router.get("/documents", summary="Knowledge-base documents (organisation or global corpus)")
async def list_documents(
    request: Request,
    ctx: OrgContext,
    scope: Literal["tenant", "global"] = "tenant",
    cursor: str | None = None,
    limit: int = 25,
) -> Page[KbDocument]:
    require(ctx, "kb.read")
    return await service.list_documents(
        request.app.state.engine, scope=scope, cursor=cursor, limit=limit
    )


@router.post(
    "/documents",
    status_code=201,
    summary="Add a document to the organisation's knowledge",
    responses={
        200: {"model": KbDocument, "description": "A document with this content already exists"}
    },
)
async def upload_document(
    request: Request,
    response: Response,
    ctx: OrgContext,
    file: UploadFile,
    kind: Annotated[
        Literal["datasheet", "application_note", "standard", "component_library", "other"],
        Form(),
    ] = "datasheet",
    manufacturer: Annotated[str, Form(max_length=120)] = "",
) -> KbDocument:
    """201 with the new document; a duplicate (same content) returns the existing document
    with 200 and is not indexed again."""
    require(ctx, "kb.write")
    name = service.safe_filename(file.filename)
    mime = service.mime_of_upload(name)
    data = await file.read(MAX_DOCUMENT + 1)
    if len(data) > MAX_DOCUMENT:
        raise ProblemError(
            413, "Payload Too Large", "document larger than 32 MB", slug="file-too-large"
        )
    state = request.app.state
    doc, created = await service.upload_document(
        state.engine,
        state.store,
        state.kb,
        state.queues,
        ctx,
        name=name,
        mime=mime,
        data=data,
        kind=kind,
        manufacturer=manufacturer,
    )
    if not created:
        response.status_code = 200
    return doc
