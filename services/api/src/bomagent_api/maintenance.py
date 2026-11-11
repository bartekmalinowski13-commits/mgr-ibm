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

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import platform_transaction, tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Queue
from bomagent_common.outbox import cleanup_sent, deliver
from bomagent_common.tenancy import TenantContext

log = get_logger(__name__)
OUTBOX_GRACE_S = 30.0  # requests deliver their own messages first


async def reap_stuck_runs(engine: AsyncEngine, tenant_id: uuid.UUID, timeout_s: float) -> int:
    """Runs left ``running`` past the timeout (worker crashed), or ``queued`` past it (the
    message went to the dead-letter queue), become ``failed`` - otherwise they would hold
    the tenant's concurrent-run quota for good."""
    ctx = TenantContext(tenant_id=tenant_id, actor_id="maintenance", actor_type="system")
    async with tenant_transaction(engine, tenant_id) as conn:
        reaped = (
            (
                await conn.execute(
                    text(
                        "UPDATE runs.runs SET status = 'failed', finished_at = now(),"
                        " error = 'TimeoutError: run did not finish in time'"
                        " WHERE (status = 'running'"
                        " AND started_at < now() - make_interval(secs => :t))"
                        " OR (status = 'queued'"
                        " AND created_at < now() - make_interval(secs => :t))"
                        " RETURNING id"
                    ),
                    {"t": timeout_s},
                )
            )
            .scalars()
            .all()
        )
        for run_id in reaped:
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
    return len(reaped)


async def sweep(
    engine: AsyncEngine,
    platform_engine: AsyncEngine,
    queues: Mapping[str, Queue],
    *,
    run_timeout_s: float,
    outbox_grace_s: float = OUTBOX_GRACE_S,
) -> dict[str, int]:
    async with platform_transaction(platform_engine) as conn:
        tenants = (await conn.execute(text("SELECT id FROM tenancy.tenants"))).scalars().all()
    totals = {"sent": 0, "reaped": 0, "purged": 0}
    for tenant_id in tenants:
        totals["sent"] += await deliver(engine, tenant_id, queues, older_than_s=outbox_grace_s)
        totals["purged"] += await cleanup_sent(engine, tenant_id)
        totals["reaped"] += await reap_stuck_runs(engine, tenant_id, run_timeout_s)
    if any(totals.values()):
        log.info("maintenance_sweep", **totals)
    return totals


def lifespan(interval_s: float, run_timeout_s: float):  # type: ignore[no-untyped-def]
    @contextlib.asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
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
