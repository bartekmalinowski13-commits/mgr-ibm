"""Parse uploaded designs (``design.uploaded``) in the sandboxed ingest worker.

Reads the design row (tenant transaction, RLS), loads the files from the tenant prefix,
runs the format parsers with size limits, writes ``parsed_design.json`` next to the files
and marks the design ``parsed`` (with format, component count, confidence, limitations)
or ``failed`` with a user-facing reason. Parser errors are permanent (acknowledged);
infrastructure errors raise so SQS retries and finally dead-letters the message.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_cad import FileRef, ParseError, parse_files
from bomagent_common import records
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message
from bomagent_common.storage import ObjectStore, tenant_key

log = get_logger(__name__)
DESIGN_UPLOADED = "design.uploaded"
MAX_FILE_BYTES = 50 * 1024 * 1024


@dataclass
class DesignIngestor:
    engine: AsyncEngine
    store: ObjectStore
    max_file_bytes: int = MAX_FILE_BYTES

    async def handle(self, message: Message) -> None:
        if message.type != DESIGN_UPLOADED:
            log.warning("message_type_ignored", message_type=message.type)
            return
        design_id = uuid.UUID(str(message.payload["design_id"]))
        ctx = message.tenant_context()
        async with tenant_transaction(self.engine, ctx.tenant_id) as conn:
            design = await records.get_design(conn, design_id)
        if design is None or design["status"] != "uploaded":
            log.warning("design_not_ready", design_id=str(design_id))
            return
        files: list[FileRef] = []
        error: str | None = None
        for name in design["filenames"]:
            key = tenant_key(ctx.tenant_id, "designs", str(design_id), "files", name)
            data = await self.store.get(key)
            if len(data) > self.max_file_bytes:
                error = f"{name} is larger than {self.max_file_bytes // (1024 * 1024)} MB"
                break
            files.append(FileRef(name=name, data=data))
        parsed = None
        if error is None:
            try:
                parsed = parse_files(files)
            except ParseError as exc:
                error = f"{exc} [{exc.code}]"
        async with tenant_transaction(self.engine, ctx.tenant_id) as conn:
            if parsed is None:
                await records.set_design_status(
                    conn, design_id, "failed", expected=("uploaded",), error=error
                )
                await emit_audit(
                    conn,
                    AuditEvent(
                        action="design.parse_failed",
                        object_type="design",
                        object_id=str(design_id),
                        after={"error": error},
                    ),
                    ctx,
                )
                log.info("design_failed", design_id=str(design_id), error=error)
                return
            parsed_key = tenant_key(ctx.tenant_id, "designs", str(design_id), "parsed_design.json")
            await self.store.put(parsed_key, parsed.model_dump_json().encode(), "application/json")
            await records.set_design_status(
                conn,
                design_id,
                "parsed",
                expected=("uploaded",),
                source_format=parsed.source_format,
                components=len(parsed.components),
                confidence=parsed.confidence,
                limitations=parsed.limitations,
                parsed_key=parsed_key,
                error=None,
            )
            await emit_audit(
                conn,
                AuditEvent(
                    action="design.parse",
                    object_type="design",
                    object_id=str(design_id),
                    after={
                        "source_format": parsed.source_format,
                        "components": len(parsed.components),
                    },
                ),
                ctx,
            )
        log.info("design_parsed", design_id=str(design_id), components=len(parsed.components))
