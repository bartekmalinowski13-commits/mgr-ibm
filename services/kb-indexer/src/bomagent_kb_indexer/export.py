"""Build the organisation data export (audit SEC-14, GDPR Art. 15/20).

``org.export.requested`` (payload ``{job_id}``) runs in the message's tenant context with
the application role, so RLS confines every query to that tenant; the ZIP is stored under
``tenants/{tenant_id}/exports/{job_id}/`` and its state is kept in ``status.json`` there.

Contents: ``manifest.json``, ``projects.json`` (projects with the metadata of their files,
not the files), ``runs.json``, ``bom/<run_id>/v<n>.json`` and ``.csv`` for every BOM
version, ``kb_documents.json`` (the organisation's own documents, metadata only) and
``audit_events.jsonl`` (the whole hash chain, so the customer can verify it).
Customer-uploaded source files and knowledge-base document bodies are not included yet.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import UTC, datetime
from typing import Any, BinaryIO, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bomagent_bom.export import to_csv
from bomagent_bom.model import BomVersion
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message
from bomagent_common.org_export import (
    EXPORT_REQUESTED,
    ExportStatus,
    archive_key,
    expiry_from,
    read_status,
    write_status,
)
from bomagent_common.storage import ObjectStore

log = get_logger(__name__)
SPOOL_BYTES = 16 * 1024 * 1024  # the ZIP is spooled to disk beyond this size
AUDIT_BATCH = 1000

PROJECT_COLS = "id, name, description, sample_key, created_by, created_at"
FILE_COLS = (
    "id, project_id, name, sha256, size_bytes, status, detected_format, created_by, created_at"
)
RUN_COLS = (
    "id, project_id, variant, runtime, model_id, status, requirements, usage, error,"
    " created_by, created_at, started_at, finished_at"
)
KB_COLS = (
    "id, title, kind, manufacturer, source_uri, mime_type, sha256, size_bytes, status,"
    " created_at, indexed_at"
)
AUDIT_COLS = (
    "seq, id, occurred_at, actor_type, actor_id, action, object_type, object_id, source_ip,"
    " request_id, trace_id, before, after, prev_hash, hash"
)


def dumps(value: Any) -> bytes:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False).encode()


def render_bom(content: dict[str, Any]) -> tuple[bytes, bytes | None]:
    """The BOM version as JSON and CSV. ``None`` for the CSV when the stored content no
    longer validates against the current model (the JSON is exported as it is)."""
    try:
        csv_text: bytes | None = to_csv(BomVersion.model_validate(content)).encode()
    except ValueError:
        csv_text = None
    return dumps(content), csv_text


async def _rows(conn: AsyncConnection, sql: str) -> list[dict[str, Any]]:
    # ``sql`` is built from constant column lists in this module, never from input
    return [dict(r._mapping) for r in await conn.execute(text(sql))]


async def _write_archive(
    conn: AsyncConnection, zf: zipfile.ZipFile, message: Message, job_id: str
) -> dict[str, int]:
    projects = await _rows(
        conn,
        f"SELECT {PROJECT_COLS} FROM projects.projects ORDER BY created_at, id",  # noqa: S608
    )
    files = await _rows(
        conn,
        f"SELECT {FILE_COLS} FROM projects.files ORDER BY created_at, id",  # noqa: S608
    )
    for project in projects:
        project["files"] = [f for f in files if f["project_id"] == project["id"]]
    zf.writestr("projects.json", dumps(projects))
    runs = await _rows(
        conn,
        f"SELECT {RUN_COLS} FROM runs.runs ORDER BY created_at, id",  # noqa: S608
    )
    zf.writestr("runs.json", dumps(runs))
    boms = 0
    skipped_csv = 0
    versions = await conn.stream(
        text(
            "SELECT run_id, version, parent_id, reason, created_by, created_at, content"
            " FROM bom.versions ORDER BY run_id, version"
        )
    )
    async for row in versions:
        as_json, as_csv = render_bom(row.content)
        base = f"bom/{row.run_id}/v{row.version}"
        zf.writestr(f"{base}.json", as_json)
        if as_csv is None:
            skipped_csv += 1
        else:
            zf.writestr(f"{base}.csv", as_csv)
        boms += 1
    kb = await _rows(
        conn,
        f"SELECT {KB_COLS} FROM kb.documents WHERE scope = 'tenant'"  # noqa: S608
        " ORDER BY created_at, id",
    )
    zf.writestr("kb_documents.json", dumps(kb))
    audit = 0
    last = 0
    with zf.open("audit_events.jsonl", "w") as out:
        while True:
            batch = (
                await conn.execute(
                    text(
                        f"SELECT {AUDIT_COLS} FROM audit.events WHERE seq > :s"  # noqa: S608
                        " ORDER BY seq LIMIT :n"
                    ),
                    {"s": last, "n": AUDIT_BATCH},
                )
            ).all()
            for row in batch:
                out.write(json.dumps(dict(row._mapping), default=str).encode() + b"\n")
                last = row.seq
            audit += len(batch)
            if len(batch) < AUDIT_BATCH:
                break
    counts = {
        "projects": len(projects),
        "files": len(files),
        "runs": len(runs),
        "bom_versions": boms,
        "kb_documents": len(kb),
        "audit_events": audit,
    }
    manifest = {
        "export_id": job_id,
        "organization_id": str(message.tenant_id),
        "generated_at": datetime.now(UTC).isoformat(),
        "requested_by": message.actor_id,
        "counts": counts,
        "bom_versions_without_csv": skipped_csv,
        "not_included": [
            "uploaded design files (their metadata and SHA-256 are in projects.json)",
            "knowledge-base document bodies and chunks",
            "members and invitations",
        ],
    }
    zf.writestr("manifest.json", dumps(manifest))
    return counts


class OrgExporter:
    """Handler of ``org.export.requested``."""

    def __init__(self, engine: AsyncEngine, store: ObjectStore) -> None:
        self._engine = engine
        self._store = store

    async def handle(self, message: Message) -> None:
        if message.type != EXPORT_REQUESTED:  # pragma: no cover - dispatcher checks
            return
        import uuid

        job_id = uuid.UUID(str(message.payload["job_id"]))
        status = await read_status(self._store, message.tenant_id, job_id)
        if status is None or status.status in {"completed", "failed"}:
            # unknown job, or a redelivered message of a finished one: nothing to do
            log.info("org_export_skipped", job_id=str(job_id), known=status is not None)
            return
        status = status.model_copy(update={"status": "running"})
        await write_status(self._store, message.tenant_id, status)
        try:
            with tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES) as spool:
                async with tenant_transaction(self._engine, message.tenant_id) as conn:
                    with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as zf:
                        counts = await _write_archive(conn, zf, message, str(job_id))
                size = spool.seek(0, 2)
                await self._store.put_file(
                    archive_key(message.tenant_id, job_id), cast(BinaryIO, spool), "application/zip"
                )
        except Exception:
            # the cause is in the log; the customer-visible state carries no internals
            log.exception("org_export_failed", job_id=str(job_id))
            status = status.model_copy(
                update={
                    "status": "failed",
                    "finished_at": datetime.now(UTC),
                    "error": "the export could not be built; request it again or contact support",
                }
            )
            await write_status(self._store, message.tenant_id, status)
            await self._audit(message, "org.export.failed", job_id, {})
            return
        status = status.model_copy(
            update={
                "status": "completed",
                "finished_at": datetime.now(UTC),
                "expires_at": expiry_from(),
                "size_bytes": size,
                "counts": counts,
            }
        )
        await write_status(self._store, message.tenant_id, status)
        await self._audit(
            message, "org.export.completed", job_id, {"size_bytes": size, "counts": counts}
        )
        log.info("org_export_completed", job_id=str(job_id), size_bytes=size)

    async def _audit(
        self, message: Message, action: str, job_id: Any, after: dict[str, Any]
    ) -> None:
        async with tenant_transaction(self._engine, message.tenant_id) as conn:
            await emit_audit(
                conn,
                AuditEvent(
                    action=action,
                    object_type="organization_export",
                    object_id=str(job_id),
                    after=after,
                ),
                message.tenant_context(),
            )


__all__ = ["ExportStatus", "OrgExporter", "render_bom"]
