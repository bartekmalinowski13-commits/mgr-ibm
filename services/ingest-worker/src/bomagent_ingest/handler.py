"""Parse uploaded design files in the sandbox (ADR-0009).

In AWS the worker runs in isolated subnets: read-only root FS, no internet route, egress
only HTTPS to VPC endpoints / own-account S3 and PostgreSQL. Parsing runs in a
resource-limited child process without the worker's environment, and the worker is
non-dumpable (``bomagent_cad.sandbox``); a project is bounded in files and bytes before
anything is downloaded.

``file.uploaded`` -> all files of the project are parsed together (KiCad hierarchies
span several files); every file row gets ``parsed``/``failed`` and the design summary
(format, components, confidence, limitations) or the error code shown in the UI.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_cad import FileRef, ParseError
from bomagent_cad.sandbox import ProjectSize, parse_files_sandboxed
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message
from bomagent_common.storage import ObjectStore, key_belongs_to

log = get_logger(__name__)
FILE_UPLOADED = "file.uploaded"


@dataclass
class IngestWorker:
    engine: AsyncEngine
    store: ObjectStore

    async def handle(self, message: Message) -> None:
        if message.type != FILE_UPLOADED:
            log.warning("message_type_ignored", message_type=message.type)
            return
        project_id = uuid.UUID(message.payload["project_id"])
        async with tenant_transaction(self.engine, message.tenant_id) as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, name, object_key, size_bytes FROM projects.files"
                        " WHERE project_id = :p ORDER BY name"
                    ),
                    {"p": project_id},
                )
            ).all()
        files: list[FileRef] = []
        for row in rows:
            if not key_belongs_to(message.tenant_id, row.object_key):
                raise ValueError("file outside the tenant prefix")
        try:
            # bounded before anything is loaded: the worker holds the project in memory
            budget = ProjectSize()
            for row in rows:
                budget.add(row.name, int(row.size_bytes or 0))
            for row in rows:
                files.append(FileRef(row.name, await self.store.get(row.object_key)))
            # CPU-bound and untrusted input: resource-limited subprocess, off the event loop
            design = await asyncio.to_thread(parse_files_sandboxed, files)
            status, fmt = "parsed", design.source_format
            summary = {
                "design": design.design_name,
                "format": design.source_format,
                "components": len(design.components),
                "confidence": design.confidence,
                "limitations": design.limitations[:20],
            }
        except ParseError as exc:
            status, fmt = "failed", None
            summary = {"error": exc.code, "message": str(exc)[:500]}
        async with tenant_transaction(self.engine, message.tenant_id) as conn:
            await conn.execute(
                text(
                    "UPDATE projects.files SET status = :s, detected_format = :f,"
                    " summary = CAST(:j AS jsonb) WHERE project_id = :p"
                ),
                {"s": status, "f": fmt, "j": json.dumps(summary), "p": project_id},
            )
            await emit_audit(
                conn,
                AuditEvent(
                    action=f"project.files_{status}",
                    object_type="project",
                    object_id=str(project_id),
                    after={"format": fmt, "files": len(files)},
                ),
            )
        log.info("project_parsed", project_id=str(project_id), status=status)
