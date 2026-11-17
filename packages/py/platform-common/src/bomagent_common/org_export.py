"""Organisation data export (GDPR Art. 15/20, audit SEC-14): job state and object keys.

The export is an asynchronous job. Its state lives next to its result in the object store
under the tenant prefix (``tenants/{tenant_id}/exports/{job_id}/``), so it needs no table:
``status.json`` is written by the API (``queued``) and the builder (``running`` ->
``completed`` / ``failed``); ``export.zip`` is the result. Every key is derived from the
tenant id (``tenant_key``), so a job id of another tenant resolves to nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from bomagent_common.storage import ObjectStore, tenant_key

EXPORT_REQUESTED = "org.export.requested"
#: how long a finished export can be downloaded (removing the file itself is a storage
#: lifecycle / retention decision of the owner - see the offboarding runbook)
EXPORT_TTL = timedelta(days=7)
#: lifetime of the signed download link
DOWNLOAD_LINK_TTL_S = 300
#: export requests an organisation may start per rolling 24 hours
MAX_EXPORTS_PER_DAY = 5

ExportState = Literal["queued", "running", "completed", "failed"]


class ExportStatus(BaseModel):
    id: uuid.UUID
    status: ExportState
    requested_by: str
    requested_at: datetime
    finished_at: datetime | None = None
    expires_at: datetime | None = None
    size_bytes: int | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


def status_key(tenant_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return tenant_key(tenant_id, "exports", str(job_id), "status.json")


def archive_key(tenant_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return tenant_key(tenant_id, "exports", str(job_id), "export.zip")


async def write_status(store: ObjectStore, tenant_id: uuid.UUID, status: ExportStatus) -> None:
    await store.put(
        status_key(tenant_id, status.id),
        status.model_dump_json().encode(),
        "application/json",
    )


def _is_missing(exc: Exception) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    error = getattr(exc, "response", {}).get("Error", {})  # botocore ClientError
    return bool(error.get("Code") in {"NoSuchKey", "404", "NotFound"})


async def read_status(
    store: ObjectStore, tenant_id: uuid.UUID, job_id: uuid.UUID
) -> ExportStatus | None:
    try:
        raw = await store.get(status_key(tenant_id, job_id))
    except Exception as exc:
        if _is_missing(exc):
            return None
        raise
    return ExportStatus.model_validate_json(raw)


def expiry_from(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + EXPORT_TTL
