"""Index knowledge-base documents announced on the ``kb`` queue.

Message types:

* ``kb.document.uploaded`` (tenant scope) - payload ``{document_id, object_key, filename}``;
  runs in the message's tenant context with the application role, so RLS confines every
  read and write to that tenant.
* ``kb.correction.requested`` (tenant scope) - payload ``{mpn, manufacturer, note}``; a
  reviewer's BOM correction becomes knowledge of that organisation only (ADR-0008).
* ``kb.global_document.uploaded`` (global corpus) - accepted only from the platform
  pseudo-tenant with ``actor_type == "system"``; uses the platform role.

Permanent failures (unsupported/corrupt file) mark the document ``failed`` and are
acknowledged; transient failures raise, so SQS retries and finally dead-letters them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_common.db import platform_transaction, tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message
from bomagent_common.storage import ObjectStore, key_belongs_to
from bomagent_kb import ExtractionError, KnowledgeBase, extract

log = get_logger(__name__)
PLATFORM_TENANT = uuid.UUID(int=0)
TENANT_UPLOAD = "kb.document.uploaded"
GLOBAL_UPLOAD = "kb.global_document.uploaded"
CORRECTION = "kb.correction.requested"


class RejectedMessageError(ValueError):
    """A message that must never be processed (forged scope, foreign object key)."""


@dataclass
class KbIndexer:
    kb: KnowledgeBase
    app_engine: AsyncEngine
    tenant_store: ObjectStore
    platform_engine: AsyncEngine | None = None
    global_store: ObjectStore | None = None
    use_docling: bool = False

    async def handle(self, message: Message) -> None:
        if message.type == TENANT_UPLOAD:
            await self._tenant(message)
        elif message.type == GLOBAL_UPLOAD:
            await self._global(message)
        elif message.type == CORRECTION:
            await self._correction(message)
        else:
            log.warning("message_type_ignored", message_type=message.type)

    async def _tenant(self, message: Message) -> None:
        doc_id = uuid.UUID(message.payload["document_id"])
        key = str(message.payload["object_key"])
        if not key_belongs_to(message.tenant_id, key):
            raise RejectedMessageError("object key outside the tenant prefix")
        data = await self.tenant_store.get(key)
        try:
            extracted = extract(
                str(message.payload["filename"]), data, use_docling=self.use_docling
            )
        except ExtractionError as exc:
            async with tenant_transaction(self.app_engine, message.tenant_id) as conn:
                await self.kb.mark_failed(conn, doc_id, str(exc))
            log.info("kb_document_failed", document_id=str(doc_id), reason=str(exc))
            return
        async with tenant_transaction(self.app_engine, message.tenant_id) as conn:
            result = await self.kb.index_document(conn, doc_id, extracted)
        log.info("kb_document_indexed", document_id=str(doc_id), chunks=result.chunks)

    async def _correction(self, message: Message) -> None:
        payload = message.payload
        async with tenant_transaction(self.app_engine, message.tenant_id) as conn:
            doc_id = await self.kb.add_correction(
                conn,
                mpn=str(payload["mpn"]),
                manufacturer=str(payload.get("manufacturer", "")),
                note=str(payload.get("note", "")),
            )
        log.info("kb_correction_indexed", document_id=str(doc_id))

    async def _global(self, message: Message) -> None:
        if message.tenant_id != PLATFORM_TENANT or message.actor_type != "system":
            raise RejectedMessageError("global corpus updates come only from the platform")
        if self.platform_engine is None or self.global_store is None:
            raise RejectedMessageError("this worker is not configured for the global corpus")
        doc_id = uuid.UUID(message.payload["document_id"])
        data = await self.global_store.get(str(message.payload["object_key"]))
        extracted = extract(str(message.payload["filename"]), data, use_docling=self.use_docling)
        async with platform_transaction(self.platform_engine) as conn:
            await self.kb.index_document(conn, doc_id, extracted)
