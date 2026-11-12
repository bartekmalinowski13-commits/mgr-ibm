"""Adding the sample projects to an organisation.

Runs under the organisation's own tenant context (RLS): every row carries the tenant id, the
objects live under the tenant prefix, and each file is queued for the sandboxed ingest-worker
through the outbox exactly like an upload. Idempotent per sample: the partial unique index
``projects_sample_key`` (migration 0014) lets a sample exist at most once per tenant, so
repeated or concurrent calls only add what is missing.

Quota decision (DECISIONS_LOG 2026-11-12): sample projects are not counted against the plan's
project limit and seeding is never refused for it; their files (a few hundred KB in total)
do count towards the storage limit, but seeding is not refused for that either.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_api.samples.catalog import SAMPLES, Sample, load_files
from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message, Queue
from bomagent_common.metering import record_usage
from bomagent_common.outbox import deliver, enqueue
from bomagent_common.storage import ObjectStore, tenant_key
from bomagent_common.tenancy import TenantContext

log = get_logger(__name__)


@dataclass
class SeedResult:
    added: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)


async def seed_samples(
    ctx: TenantContext,
    *,
    engine: AsyncEngine,
    store: ObjectStore,
    queues: dict[str, Queue],
    trigger: str,
) -> SeedResult:
    """Add every missing sample to the organisation of ``ctx``; audited as
    ``org.samples_seeded`` when anything was added."""
    result = SeedResult()
    outbox_ids: list[uuid.UUID] = []
    for sample in SAMPLES:
        ids = await _add_one(ctx, engine, store, sample)
        if ids is None:
            result.existing.append(sample.key)
        else:
            result.added.append(sample.key)
            outbox_ids.extend(ids)
    if result.added:
        async with tenant_transaction(engine, ctx.tenant_id) as conn:
            await emit_audit(
                conn,
                AuditEvent(
                    action="org.samples_seeded",
                    object_type="organization",
                    object_id=str(ctx.tenant_id),
                    after={"added": sorted(result.added), "trigger": trigger},
                ),
                ctx,
            )
        try:  # committed outbox rows: on failure the relay sends them later
            await deliver(engine, ctx.tenant_id, queues, ids=outbox_ids)
        except Exception:
            log.warning("samples_outbox_deliver_deferred", tenant_id=str(ctx.tenant_id))
    result.added.sort()
    result.existing.sort()
    return result


async def _add_one(
    ctx: TenantContext, engine: AsyncEngine, store: ObjectStore, sample: Sample
) -> list[uuid.UUID] | None:
    """Create one sample project with its files; ``None`` when it already exists."""
    pid = uuid.uuid4()
    written: list[str] = []
    try:
        async with tenant_transaction(engine, ctx.tenant_id) as conn:
            created = (
                await conn.execute(
                    text(
                        "INSERT INTO projects.projects (id, tenant_id, name, description,"
                        " created_by, sample_key) VALUES (:i, app.current_tenant_id(), :n,"
                        " :d, :u, :k) ON CONFLICT (tenant_id, sample_key)"
                        " WHERE sample_key IS NOT NULL DO NOTHING RETURNING id"
                    ),
                    {
                        "i": pid,
                        "n": sample.project_name,
                        "d": sample.description,
                        "u": ctx.actor_id,
                        "k": sample.key,
                    },
                )
            ).first()
            if created is None:
                return None
            total = 0
            for name, data in load_files(sample):
                fid = uuid.uuid4()
                key = tenant_key(ctx.tenant_id, "projects", str(pid), str(fid), name)
                await store.put(key, data, "application/octet-stream")
                written.append(key)
                await conn.execute(
                    text(
                        "INSERT INTO projects.files (id, tenant_id, project_id, name,"
                        " object_key, sha256, size_bytes, created_by) VALUES (:i,"
                        " app.current_tenant_id(), :p, :n, :k, :h, :s, :u)"
                    ),
                    {
                        "i": fid,
                        "p": pid,
                        "n": name,
                        "k": key,
                        "h": hashlib.sha256(data).hexdigest(),
                        "s": len(data),
                        "u": ctx.actor_id,
                    },
                )
                total += len(data)
            await emit_audit(
                conn,
                AuditEvent(
                    action="project.created",
                    object_type="project",
                    object_id=str(pid),
                    after={
                        "name": sample.project_name,
                        "sample": sample.key,
                        "files": [n for n, _ in load_files(sample)],
                    },
                ),
                ctx,
            )
            await record_usage(conn, files_uploaded=len(sample.files), bytes_uploaded=total)
            # the ingest-worker parses a whole project per message: one is enough
            return [
                await enqueue(
                    conn,
                    "ingest",
                    Message.create("file.uploaded", ctx, {"project_id": str(pid)}),
                )
            ]
    except BaseException:
        for key in written:  # the transaction was not committed: drop the new objects
            await store.delete(key)
        raise
