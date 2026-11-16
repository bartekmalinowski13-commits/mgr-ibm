"""Periodic maintenance in the API process: outbox relay and stuck-run reaper.

Tenants are listed with the platform role (allowed to read ``tenancy.tenants``); all
tenant data is then touched only in that tenant's own RLS context. Several replicas may
run this concurrently: outbox rows are taken with SKIP LOCKED, reaping is a conditional
UPDATE.
"""

from __future__ import annotations

import asyncio
import contextlib
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
from bomagent_common.messaging import Queue
from bomagent_common.outbox import cleanup_sent, deliver
from bomagent_common.tenancy import TenantContext

log = get_logger(__name__)
OUTBOX_GRACE_S = 30.0  # requests deliver their own messages first
_anchored: dict[uuid.UUID, date] = {}  # tenant -> day its anchor was written (this process)


async def reap_stuck_runs(engine: AsyncEngine, tenant_id: uuid.UUID, timeout_s: float) -> int:
    """Runs left ``running`` past the timeout (worker crashed), or ``queued`` past it (the
    message went to the dead-letter queue), become ``failed`` - otherwise they would hold
    the tenant's concurrent-run quota for good."""
    ctx = TenantContext(tenant_id=tenant_id, actor_id="maintenance", actor_type="system")
    async with tenant_transaction(engine, tenant_id) as conn:
        reaped = (
            await conn.execute(
                text(
                    "UPDATE runs.runs SET status = 'failed', finished_at = now(),"
                    " error = 'TimeoutError: run did not finish in time'"
                    " WHERE (status = 'running'"
                    " AND started_at < now() - make_interval(secs => :t))"
                    " OR (status = 'queued'"
                    " AND created_at < now() - make_interval(secs => :t))"
                    " RETURNING id, variant"
                ),
                {"t": timeout_s},
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
    totals = {"sent": 0, "reaped": 0, "purged": 0}
    today = datetime.now(UTC).date()
    for tenant_id in tenants:
        if anchor_sink is not None and _anchored.get(tenant_id) != today:
            try:  # the chain head goes to write-once storage once a day (ADR-0011)
                await export_anchor(engine, anchor_sink, tenant_id)
                _anchored[tenant_id] = today
            except Exception:
                log.exception("audit_anchor_export_failed", tenant_id=str(tenant_id))
        totals["sent"] += await deliver(engine, tenant_id, queues, older_than_s=outbox_grace_s)
        totals["purged"] += await cleanup_sent(engine, tenant_id)
        totals["reaped"] += await reap_stuck_runs(engine, tenant_id, run_timeout_s)
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
