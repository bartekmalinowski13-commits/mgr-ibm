"""Periodic maintenance in the API process: outbox relay, stuck-run reaper and the reaper of
files / knowledge-base documents whose queue message dead-lettered.

Tenants are listed with the platform role (allowed to read ``tenancy.tenants``); all
tenant data is then touched only in that tenant's own RLS context. Several replicas may
run this concurrently: outbox rows are taken with SKIP LOCKED, reaping is a conditional
UPDATE.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, date, datetime

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_common import metrics
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.audit_anchor import AnchorSink, export_anchor
from bomagent_common.db import platform_transaction, tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import (
    MAX_RECEIVE_COUNT,
    QUEUE_VISIBILITY_S,
    RUN_RESUME_STALE_S,
    Queue,
)
from bomagent_common.outbox import cleanup_sent, deliver
from bomagent_common.tenancy import TenantContext

log = get_logger(__name__)
OUTBOX_GRACE_S = 30.0  # requests deliver their own messages first
ANCHOR_TIMEOUT_S = 15.0
RATE_WINDOW_TTL_S = 3600.0  # windows are one minute long; an hour is far past any retry
IDEMPOTENCY_TTL_S = 24 * 3600.0  # a retry after a day is a new request (SEC-17)
#: a running run is never reaped within this long of its start/takeover: a worker killed
#: without handing its message back leaves it invisible for the runs queue's visibility
#: timeout, and the redelivery takes the run over once it has been idle for the resume
#: threshold - the reaper must not fall due in that same window (+ a sweep's margin)
RUNNING_REAP_GRACE_S = QUEUE_VISIBILITY_S["runs"] + RUN_RESUME_STALE_S + 300.0
#: a message is retried for at most visibility x receives before it dead-letters; an hour of
#: grace covers a backlog before the first receive
INGEST_TIMEOUT_S = QUEUE_VISIBILITY_S["ingest"] * MAX_RECEIVE_COUNT + 3600.0
KB_INDEX_TIMEOUT_S = QUEUE_VISIBILITY_S["kb"] * MAX_RECEIVE_COUNT + 3600.0
INGEST_TIMEOUT_ERROR = "ingest.timeout"
INGEST_TIMEOUT_MESSAGE = (
    "The file could not be processed in time and was not checked or parsed. Upload it again;"
    " if this keeps happening, contact support."
)
KB_TIMEOUT_ERROR = "indexing did not finish in time; upload the document again"
_anchored: dict[uuid.UUID, date] = {}  # tenant -> day its anchor was written (this process)


async def reap_stuck_runs(engine: AsyncEngine, tenant_id: uuid.UUID, timeout_s: float) -> int:
    """Runs left ``running`` and idle past the timeout (worker crashed and the run was not
    resumed), or ``queued`` past it (the message went to the dead-letter queue), become
    ``failed`` - otherwise they would hold the tenant's concurrent-run quota for good.

    A running run's idle time counts from its start, takeover or last checkpoint, whichever
    is latest, and it is never reaped within ``RUNNING_REAP_GRACE_S`` of its start/takeover:
    an interrupted run is redelivered and resumed first, and a run that still checkpoints is
    not killed."""
    ctx = TenantContext(tenant_id=tenant_id, actor_id="maintenance", actor_type="system")
    async with tenant_transaction(engine, tenant_id) as conn:
        reaped = (
            await conn.execute(
                text(
                    "UPDATE runs.runs SET status = 'failed', finished_at = now(),"
                    " error = 'TimeoutError: run did not finish in time'"
                    " WHERE (status = 'running'"
                    " AND started_at < now() - make_interval(secs => greatest(:t, :g))"
                    " AND NOT EXISTS (SELECT 1 FROM runs.graph_checkpoints c"
                    "  WHERE c.run_id = runs.runs.id"
                    "  AND c.created_at >= now() - make_interval(secs => :t)))"
                    " OR (status = 'queued'"
                    " AND created_at < now() - make_interval(secs => :t))"
                    " RETURNING id, variant"
                ),
                {"t": timeout_s, "g": RUNNING_REAP_GRACE_S},
            )
        ).all()
        for run_id, _variant in reaped:
            await emit_audit(
                conn,
                AuditEvent(
                    action="run.failed",
                    object_type="run",
                    object_id=str(run_id),
                    after={"error": "timeout", "by": "maintenance"},
                ),
                ctx,
            )
    # counted after the commit; a crashed or hung worker never records its own failure
    for _run_id, variant in reaped:
        metrics.record_run("failed", str(variant), duration_s=-1)
    return len(reaped)


async def fail_stale_ingest(
    engine: AsyncEngine, tenant_id: uuid.UUID, timeout_s: float = INGEST_TIMEOUT_S
) -> int:
    """Files still ``uploaded`` long after their upload (the ingest message dead-lettered:
    scanner outage, worker crash) become ``failed`` with a reason the UI shows, audited per
    project. A late message for unchanged files still writes its verdict over this."""
    ctx = TenantContext(tenant_id=tenant_id, actor_id="maintenance", actor_type="system")
    async with tenant_transaction(engine, tenant_id) as conn:
        failed = (
            await conn.execute(
                text(
                    "UPDATE projects.files SET status = 'failed', detected_format = NULL,"
                    " summary = CAST(:j AS jsonb) WHERE status = 'uploaded'"
                    " AND created_at < now() - make_interval(secs => :t)"
                    " RETURNING project_id, name"
                ),
                {
                    "t": timeout_s,
                    "j": json.dumps(
                        {"error": INGEST_TIMEOUT_ERROR, "message": INGEST_TIMEOUT_MESSAGE}
                    ),
                },
            )
        ).all()
        by_project: dict[uuid.UUID, list[str]] = {}
        for project_id, name in failed:
            by_project.setdefault(project_id, []).append(name)
        for project_id, names in by_project.items():
            await emit_audit(
                conn,
                AuditEvent(
                    action="project.files_failed",
                    object_type="project",
                    object_id=str(project_id),
                    after={"error": INGEST_TIMEOUT_ERROR, "files": names[:20], "by": "maintenance"},
                ),
                ctx,
            )
    for _ in failed:
        metrics.record_parse("failed", INGEST_TIMEOUT_ERROR, duration_s=-1)
    return len(failed)


_STALE_DOCUMENTS = (
    "UPDATE kb.documents SET status = 'failed', error = :e"
    " WHERE scope = :scope AND status IN ('pending', 'indexing') AND superseded_at IS NULL"
    " AND created_at < now() - make_interval(secs => :t) RETURNING id"
)


async def fail_stale_documents(
    engine: AsyncEngine, tenant_id: uuid.UUID, timeout_s: float = KB_INDEX_TIMEOUT_S
) -> int:
    """The tenant's KB documents still ``pending``/``indexing`` past the retry window
    become ``failed`` with a reason (shown in the KB list), audited."""
    ctx = TenantContext(tenant_id=tenant_id, actor_id="maintenance", actor_type="system")
    async with tenant_transaction(engine, tenant_id) as conn:
        failed = (
            (
                await conn.execute(
                    text(_STALE_DOCUMENTS),
                    {"e": KB_TIMEOUT_ERROR, "scope": "tenant", "t": timeout_s},
                )
            )
            .scalars()
            .all()
        )
        for doc_id in failed:
            await emit_audit(
                conn,
                AuditEvent(
                    action="kb.document.failed",
                    object_type="kb_document",
                    object_id=str(doc_id),
                    after={"error": "timeout", "by": "maintenance"},
                ),
                ctx,
            )
    return len(failed)


async def fail_stale_global_documents(
    platform_engine: AsyncEngine, timeout_s: float = KB_INDEX_TIMEOUT_S
) -> int:
    """Same for the global corpus (platform role; there is no tenant audit chain)."""
    async with platform_transaction(platform_engine) as conn:
        failed = (
            (
                await conn.execute(
                    text(_STALE_DOCUMENTS),
                    {"e": KB_TIMEOUT_ERROR, "scope": "global", "t": timeout_s},
                )
            )
            .scalars()
            .all()
        )
    for doc_id in failed:
        log.warning("kb_global_document_timed_out", document_id=str(doc_id))
    return len(failed)


async def expire_idempotency_keys(
    engine: AsyncEngine, tenant_id: uuid.UUID, ttl_s: float = IDEMPOTENCY_TTL_S
) -> int:
    """Stored responses of ``Idempotency-Key`` requests are only useful for retries; they would
    otherwise grow for ever. Runs through the tenant context, so RLS limits it to the tenant."""
    async with tenant_transaction(engine, tenant_id) as conn:
        result = await conn.execute(
            text(
                "DELETE FROM app.idempotency_keys"
                " WHERE created_at < now() - make_interval(secs => :t)"
            ),
            {"t": ttl_s},
        )
    return int(result.rowcount or 0)


async def expire_rate_windows(
    engine: AsyncEngine, tenant_id: uuid.UUID, ttl_s: float = RATE_WINDOW_TTL_S
) -> int:
    """Rate-limit counters are one-minute windows; a request only cleans up its own subject's
    old windows, so those of subjects that never come back (removed members, rotated API keys)
    would stay for ever (DATA-01). Tenant context, so RLS limits it to the tenant."""
    async with tenant_transaction(engine, tenant_id) as conn:
        result = await conn.execute(
            text(
                "DELETE FROM app.rate_windows"
                " WHERE window_start < now() - make_interval(secs => :t)"
            ),
            {"t": ttl_s},
        )
    return int(result.rowcount or 0)


async def sweep(
    engine: AsyncEngine,
    platform_engine: AsyncEngine,
    queues: Mapping[str, Queue],
    *,
    run_timeout_s: float,
    outbox_grace_s: float = OUTBOX_GRACE_S,
    anchor_sink: AnchorSink | None = None,
) -> dict[str, int]:
    async with platform_transaction(platform_engine) as conn:
        tenants = (await conn.execute(text("SELECT id FROM tenancy.tenants"))).scalars().all()
    totals = {
        "sent": 0,
        "reaped": 0,
        "purged": 0,
        "expired_keys": 0,
        "expired_windows": 0,
        "stale_files": 0,
        "stale_documents": await fail_stale_global_documents(platform_engine),
    }
    now = datetime.now(UTC)
    today = now.date()
    anchoring = anchor_sink is not None
    for tenant_id in tenants:
        if anchoring and anchor_sink is not None and _anchored.get(tenant_id) != today:
            try:  # the chain head goes to write-once storage once a day (ADR-0011)
                await asyncio.wait_for(
                    export_anchor(engine, anchor_sink, tenant_id, now), ANCHOR_TIMEOUT_S
                )
                _anchored[tenant_id] = today
            except Exception:
                # a failing sink must not hold up delivery and reaping for every tenant: skip
                # the rest of this sweep's anchors, the next sweep retries
                log.exception("audit_anchor_export_failed", tenant_id=str(tenant_id))
                anchoring = False
        totals["sent"] += await deliver(engine, tenant_id, queues, older_than_s=outbox_grace_s)
        totals["purged"] += await cleanup_sent(engine, tenant_id)
        totals["reaped"] += await reap_stuck_runs(engine, tenant_id, run_timeout_s)
        totals["expired_keys"] += await expire_idempotency_keys(engine, tenant_id)
        totals["expired_windows"] += await expire_rate_windows(engine, tenant_id)
        totals["stale_files"] += await fail_stale_ingest(engine, tenant_id)
        totals["stale_documents"] += await fail_stale_documents(engine, tenant_id)
    if any(totals.values()):
        log.info("maintenance_sweep", **totals)
    return totals


def lifespan(  # type: ignore[no-untyped-def]
    interval_s: float, run_timeout_s: float, anchor_sink: AnchorSink | None = None
):
    @contextlib.asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.anchor_sink = anchor_sink  # read by GET /v1/audit-events/verify
        stop = asyncio.Event()

        async def loop() -> None:
            while not stop.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=interval_s)
                if stop.is_set():
                    break
                try:
                    await sweep(
                        app.state.engine,
                        app.state.platform_engine,
                        app.state.queues,
                        run_timeout_s=run_timeout_s,
                        anchor_sink=anchor_sink,
                    )
                except Exception:
                    log.exception("maintenance_sweep_failed")

        task = None
        if interval_s > 0 and app.state.engine is not None and app.state.platform_engine:
            task = asyncio.create_task(loop())
        try:
            yield
        finally:
            stop.set()
            if task is not None:
                await task

    return _lifespan
