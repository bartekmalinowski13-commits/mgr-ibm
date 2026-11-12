"""Outbox: retry limit with dead rows, and cleanup of old sent rows."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from bomagent_common.db import tenant_transaction
from bomagent_common.messaging import InMemoryQueue, Message
from bomagent_common.outbox import cleanup_sent, deliver, enqueue
from bomagent_common.tenancy import tenant_scope

pytestmark = pytest.mark.integration


class DownQueue(InMemoryQueue):
    async def send(self, message: Message) -> None:
        raise ConnectionError("down")


async def _enqueue(app_engine, tenant) -> uuid.UUID:
    with tenant_scope(tenant):
        msg = Message.create("file.uploaded", tenant, {"file_id": "f"})
        async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
            return await enqueue(conn, "ingest", msg)


async def test_a_short_outage_does_not_kill_young_rows(app_engine, make_tenant):
    tenant = await make_tenant()
    oid = await _enqueue(app_engine, tenant)
    for _ in range(5):  # many sweeps (several replicas) during a short SQS outage
        await deliver(app_engine, tenant.tenant_id, {"ingest": DownQueue()}, max_attempts=3)
    ok = InMemoryQueue()
    assert await deliver(app_engine, tenant.tenant_id, {"ingest": ok}, max_attempts=3) == 1
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        dead = await conn.scalar(text("SELECT dead_at FROM app.outbox WHERE id = :i"), {"i": oid})
    assert dead is None


async def test_rows_die_after_max_attempts_and_are_not_retried(app_engine, make_tenant):
    tenant = await make_tenant()
    oid = await _enqueue(app_engine, tenant)
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await conn.execute(
            text("UPDATE app.outbox SET created_at = now() - interval '2 days' WHERE id = :i"),
            {"i": oid},
        )
    queues = {"ingest": DownQueue()}
    for _ in range(3):
        await deliver(app_engine, tenant.tenant_id, queues, max_attempts=3)
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        row = (
            await conn.execute(
                text("SELECT attempts, last_error, dead_at FROM app.outbox WHERE id = :i"),
                {"i": oid},
            )
        ).one()
    assert row.attempts == 3
    assert row.last_error == "ConnectionError"
    assert row.dead_at is not None
    ok = InMemoryQueue()
    assert await deliver(app_engine, tenant.tenant_id, {"ingest": ok}, max_attempts=3) == 0
    assert len(ok) == 0


async def test_cleanup_removes_only_old_sent_rows(app_engine, make_tenant):
    tenant = await make_tenant()
    old, recent, pending = [await _enqueue(app_engine, tenant) for _ in range(3)]
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await conn.execute(
            text("UPDATE app.outbox SET sent_at = now() - interval '8 days' WHERE id = :i"),
            {"i": old},
        )
        await conn.execute(
            text("UPDATE app.outbox SET sent_at = now() - interval '1 day' WHERE id = :i"),
            {"i": recent},
        )
    removed = await cleanup_sent(app_engine, tenant.tenant_id, older_than_days=7)
    assert removed == 1
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        ids = set((await conn.execute(text("SELECT id FROM app.outbox"))).scalars())
    assert ids == {recent, pending}
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await conn.execute(text("DELETE FROM app.outbox"))  # the database is shared by tests


async def test_a_row_whose_message_names_another_tenant_is_never_sent(app_engine, make_tenant):
    tenant, other = await make_tenant(), await make_tenant()
    with tenant_scope(tenant):
        forged = Message.create("file.uploaded", other, {"file_id": "f"})
        async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO app.outbox (id, tenant_id, queue, message) VALUES"
                    " (gen_random_uuid(), app.current_tenant_id(), 'ingest', CAST(:m AS jsonb))"
                ),
                {"m": forged.model_dump_json()},
            )
    ok = InMemoryQueue()
    assert await deliver(app_engine, tenant.tenant_id, {"ingest": ok}) == 0
    assert len(ok) == 0
    async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
        await conn.execute(text("DELETE FROM app.outbox"))
