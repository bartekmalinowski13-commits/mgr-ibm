"""Isolation of the PostgreSQL queue (``app.queue_messages``, migration 0013)."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from bomagent_common.db import platform_transaction, tenant_transaction
from bomagent_common.messaging import Message, PostgresQueue

pytestmark = [pytest.mark.integration, pytest.mark.isolation]

INSERT = (
    "INSERT INTO app.queue_messages (id, tenant_id, queue, message)"
    " VALUES (:i, :t, :q, CAST(:m AS jsonb))"
)


def _params(tenant, queue: str) -> dict:
    msg = Message.create("x.y", tenant)
    return {"i": uuid.uuid4(), "t": tenant.tenant_id, "q": queue, "m": msg.model_dump_json()}


async def test_app_role_inserts_only_its_own_tenant(app_engine, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    queue = f"iso-{uuid.uuid4().hex[:8]}"
    async with tenant_transaction(app_engine, a.tenant_id) as conn:
        await conn.execute(text(INSERT), _params(a, queue))
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_transaction(app_engine, a.tenant_id) as conn:
            await conn.execute(text(INSERT), _params(b, queue))
    with pytest.raises(DBAPIError, match="row-level security"):  # no context, no rows
        async with platform_transaction(app_engine) as conn:
            await conn.execute(text(INSERT), _params(a, queue))


@pytest.mark.parametrize(
    "stmt",
    [
        "SELECT count(*) FROM app.queue_messages",
        "UPDATE app.queue_messages SET visible_at = now()",
        "DELETE FROM app.queue_messages",
    ],
)
async def test_app_role_cannot_read_or_consume_messages(app_engine, make_tenant, stmt):
    a, b = await make_tenant(), await make_tenant()
    queue = PostgresQueue(f"iso-{uuid.uuid4().hex[:8]}", producer_engine=app_engine)
    await queue.send(Message.create("x.y", b))
    for tenant in (a, b):  # not even its own tenant's rows: consuming is the platform's job
        with pytest.raises(DBAPIError, match="permission denied"):
            async with tenant_transaction(app_engine, tenant.tenant_id) as conn:
                await conn.execute(text(stmt))


async def test_platform_role_cannot_forge_or_retarget_messages(
    app_engine, platform_engine, make_tenant
):
    a, b = await make_tenant(), await make_tenant()
    queue = PostgresQueue(f"iso-{uuid.uuid4().hex[:8]}", producer_engine=app_engine)
    await queue.send(Message.create("x.y", a))
    with pytest.raises(DBAPIError, match="permission denied"):
        async with platform_transaction(platform_engine) as conn:
            await conn.execute(text(INSERT), _params(b, queue.name))
    for assignment, value in (
        ("tenant_id = CAST(:v AS uuid)", str(b.tenant_id)),
        ("message = CAST(:v AS jsonb)", json.dumps({"type": "forged"})),
        ("queue = :v", "runs"),
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with platform_transaction(platform_engine) as conn:
                await conn.execute(
                    text(f"UPDATE app.queue_messages SET {assignment} WHERE queue = :q"),
                    {"v": value, "q": queue.name},
                )


async def test_consumer_restores_the_tenant_of_each_message(
    app_engine, platform_engine, make_tenant
):
    a, b = await make_tenant(), await make_tenant()
    queue = PostgresQueue(
        f"iso-{uuid.uuid4().hex[:8]}", producer_engine=app_engine, consumer_engine=platform_engine
    )
    for t in (a, b):
        await queue.send(Message.create("x.y", t))
    items = await queue.receive(wait_seconds=0)
    assert sorted(i.message.tenant_id for i in items) == sorted([a.tenant_id, b.tenant_id])
    for item in items:
        assert item.message.tenant_context().tenant_id == item.message.tenant_id
        await queue.ack(item)
