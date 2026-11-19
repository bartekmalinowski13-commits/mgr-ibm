"""Parse uploaded design files in the sandbox (ADR-0009).

In AWS the worker runs in isolated subnets: read-only root FS, no internet route, egress
only HTTPS to VPC endpoints / own-account S3 and PostgreSQL. Parsing runs in a
resource-limited child process without the worker's environment, and the worker is
non-dumpable (``bomagent_cad.sandbox``); a project is bounded in files and bytes before
anything is downloaded.

``file.uploaded`` -> all files of the project are parsed together (KiCad hierarchies
span several files); every file row gets ``parsed``/``failed`` and the design summary
(format, components, confidence, limitations) or the error code shown in the UI.

Only the rows that were actually loaded and scanned are written back, compared by id,
object key and hash under a row lock: a file replaced while the message was handled keeps
``uploaded`` (its new bytes were never scanned) and is handled by its own message. When
the project's file set changed meanwhile, only rows still waiting for a verdict are
written, so a stale result never overwrites a newer one.

Failures that retrying cannot fix are terminal and acknowledged: malware, a file the
scanner refuses (``file.scan_failed``), parser errors, an object key outside the tenant
(audited; the files are left to the maintenance sweep). Scanner outages raise and are
retried; a message that dead-letters leaves files ``uploaded`` until the API's maintenance
sweep fails them (``ingest.timeout``). Scanning has a total budget (``SCAN_BUDGET_S``) so
that scan + parse stay inside the queue's visibility timeout.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bomagent_cad import FileRef, ParseError
from bomagent_cad.sandbox import ProjectSize, parse_files_sandboxed
from bomagent_common import metrics
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message
from bomagent_common.storage import ObjectStore, key_belongs_to
from bomagent_ingest.scanner import (
    FileScanner,
    MalwareDetectedError,
    ScannerError,
    ScanRejectedError,
    ScanResult,
    scanner_from_env,
)

log = get_logger(__name__)
FILE_UPLOADED = "file.uploaded"
MALWARE_ERROR = "file.rejected"
# deliberately generic: no signature name, no hint about which scanner or which file
MALWARE_MESSAGE = (
    "A file in this project was rejected by the security check and nothing was processed. "
    "Remove the file and upload the project again."
)
SCAN_FAILED_ERROR = "file.scan_failed"
SCAN_FAILED_MESSAGE = (
    "A file in this project could not be checked by the security scan (it is probably too"
    " large for the scanner) and nothing was processed. Upload a smaller export of the design."
)
#: files scanned at once, and the total time for scanning one project: with the sandbox's
#: wall clock (90 s) this stays well inside the ingest visibility timeout (600 s)
SCAN_CONCURRENCY = 4
SCAN_BUDGET_S = 300.0


@dataclass
class IngestWorker:
    engine: AsyncEngine
    store: ObjectStore
    # ClamAV when BOMAGENT_MALWARE_SCAN_CLAMD_ADDR is set, else the EICAR-only scanner (SEC-09)
    scanner: FileScanner = field(default_factory=scanner_from_env)
    scan_budget_s: float = SCAN_BUDGET_S

    async def _scan_one(self, f: FileRef, gate: asyncio.Semaphore) -> ScanResult | ScannerError:
        async with gate:
            started = time.monotonic()
            try:
                result = await self.scanner.scan(f.name, f.data)
            except ScannerError as exc:
                metrics.record_malware_scan("error", duration_s=time.monotonic() - started)
                return exc
            metrics.record_malware_scan(
                "clean" if result.clean else "infected", duration_s=time.monotonic() - started
            )
            return result

    async def _scan_all(self, files: list[FileRef]) -> None:
        """Scan every file before any parser runs, a few at a time and within the budget.

        Raises :class:`MalwareDetectedError` (any file infected), :class:`ScanRejectedError`
        (a file the scanner can never scan) or :class:`ScannerError` (outage, deadline):
        nothing is "clean" unless every file was scanned clean."""
        gate = asyncio.Semaphore(SCAN_CONCURRENCY)
        try:
            async with asyncio.timeout(self.scan_budget_s):
                results = await asyncio.gather(*(self._scan_one(f, gate) for f in files))
        except TimeoutError as exc:
            raise ScannerError(
                f"malware scan deadline exceeded ({self.scan_budget_s:g} s)"
            ) from exc
        findings = {
            f.name: r.signature or "unknown"
            for f, r in zip(files, results, strict=True)
            if isinstance(r, ScanResult) and not r.clean
        }
        if findings:
            raise MalwareDetectedError(findings)
        errors = [r for r in results if isinstance(r, ScannerError)]
        permanent = [e for e in errors if isinstance(e, ScanRejectedError)]
        if permanent:
            raise permanent[0]
        if errors:
            raise errors[0]  # fail closed: not clean, the message is retried

    async def _reject_foreign_keys(
        self, message: Message, project_id: uuid.UUID, names: list[str]
    ) -> None:
        """Never retried (it cannot succeed): audited, and the files stay ``uploaded`` until
        the maintenance sweep fails them."""
        log.error("ingest_foreign_object_key", project_id=str(project_id), files=len(names))
        async with tenant_transaction(self.engine, message.tenant_id) as conn:
            await emit_audit(
                conn,
                AuditEvent(
                    action="project.ingest_rejected",
                    object_type="project",
                    object_id=str(project_id),
                    after={"reason": "object key outside the tenant prefix", "files": names[:20]},
                ),
            )

    async def handle(self, message: Message) -> None:
        if message.type != FILE_UPLOADED:
            log.warning("message_type_ignored", message_type=message.type)
            return
        project_id = uuid.UUID(message.payload["project_id"])
        async with tenant_transaction(self.engine, message.tenant_id) as conn:
            exists = (
                await conn.execute(
                    text("SELECT 1 FROM projects.projects WHERE id = :p"), {"p": project_id}
                )
            ).first()
            if exists is None:  # deleted after the message was queued: nothing to parse
                log.info("project_gone_skipped", project_id=str(project_id))
                return
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, name, object_key, sha256, size_bytes FROM projects.files"
                        " WHERE project_id = :p ORDER BY name"
                    ),
                    {"p": project_id},
                )
            ).all()
        foreign = [r.name for r in rows if not key_belongs_to(message.tenant_id, r.object_key)]
        if foreign:
            await self._reject_foreign_keys(message, project_id, foreign)
            return
        # exactly what this message loads and scans: (object key, hash) per file id
        loaded = {row.id: (row.object_key, row.sha256) for row in rows}
        files: list[FileRef] = []
        events: list[tuple[str, dict[str, object]]] = []  # audit (action, after)
        started = time.monotonic()
        try:
            # bounded before anything is loaded: the worker holds the project in memory
            budget = ProjectSize()
            for row in rows:
                budget.add(row.name, int(row.size_bytes or 0))
            for row in rows:
                files.append(FileRef(row.name, await self.store.get(row.object_key)))
            await self._scan_all(files)  # before any parser touches the bytes (SEC-09)
            # CPU-bound and untrusted input: resource-limited subprocess, off the event loop
            design = await asyncio.to_thread(parse_files_sandboxed, files)
            metrics.record_parse("ok", None, duration_s=time.monotonic() - started)
            status, fmt = "parsed", design.source_format
            summary = {
                "design": design.design_name,
                "format": design.source_format,
                "components": len(design.components),
                "confidence": design.confidence,
                "limitations": design.limitations[:20],
            }
        except MalwareDetectedError as exc:
            log.warning(
                "file_malware_detected", project_id=str(project_id), files=len(exc.findings)
            )
            findings = dict(list(exc.findings.items())[:20])
            events.append(("project.file_malware_detected", {"findings": findings}))
            metrics.record_parse("failed", MALWARE_ERROR, duration_s=time.monotonic() - started)
            status, fmt = "failed", None
            summary = {"error": MALWARE_ERROR, "message": MALWARE_MESSAGE}
        except ScanRejectedError as exc:
            events.append(
                ("project.file_scan_failed", {"error": SCAN_FAILED_ERROR, "files": len(loaded)})
            )
            log.warning("file_scan_rejected", project_id=str(project_id), reason=str(exc)[:200])
            metrics.record_parse("failed", SCAN_FAILED_ERROR, duration_s=time.monotonic() - started)
            status, fmt = "failed", None
            summary = {"error": SCAN_FAILED_ERROR, "message": SCAN_FAILED_MESSAGE}
        except ParseError as exc:
            metrics.record_parse("failed", exc.code, duration_s=time.monotonic() - started)
            status, fmt = "failed", None
            summary = {"error": exc.code, "message": str(exc)[:500]}
        async with tenant_transaction(self.engine, message.tenant_id) as conn:
            written = await _write_back(conn, project_id, loaded, status, fmt, summary)
            if written:
                events.insert(0, (f"project.files_{status}", {"format": fmt, "files": written}))
            for action, after in events:  # security events are audited even if nothing changed
                await emit_audit(
                    conn,
                    AuditEvent(
                        action=action,
                        object_type="project",
                        object_id=str(project_id),
                        after=after,
                    ),
                )
        log.info("project_parsed", project_id=str(project_id), status=status, files=written)


async def _write_back(
    conn: AsyncConnection,
    project_id: uuid.UUID,
    loaded: dict[uuid.UUID, tuple[str, str]],
    status: str,
    fmt: str | None,
    summary: dict[str, object],
) -> int:
    """Write the verdict to the rows this message loaded and scanned; returns their count.

    The project's rows are locked and compared with ``loaded`` (id -> object key, hash): a
    row replaced meanwhile is skipped. If the file set changed at all (replaced, added or
    deleted), only rows still ``uploaded`` are written - a newer message has handled, or will
    handle, the others together with the current set."""
    current = {
        row.id: row
        for row in (
            await conn.execute(
                text(
                    "SELECT id, object_key, sha256, status FROM projects.files"
                    " WHERE project_id = :p FOR UPDATE"
                ),
                {"p": project_id},
            )
        ).all()
    }
    same = [
        fid
        for fid, (key, sha) in loaded.items()
        if fid in current and (current[fid].object_key, current[fid].sha256) == (key, sha)
    ]
    if not len(same) == len(loaded) == len(current):
        same = [fid for fid in same if current[fid].status == "uploaded"]
        log.info(
            "ingest_file_set_changed",
            project_id=str(project_id),
            loaded=len(loaded),
            written=len(same),
        )
    if not same:
        return 0
    await conn.execute(
        text(
            "UPDATE projects.files SET status = :s, detected_format = :f,"
            " summary = CAST(:j AS jsonb) WHERE project_id = :p AND id = ANY(:ids)"
        ),
        {"s": status, "f": fmt, "j": json.dumps(summary), "p": project_id, "ids": same},
    )
    return len(same)
