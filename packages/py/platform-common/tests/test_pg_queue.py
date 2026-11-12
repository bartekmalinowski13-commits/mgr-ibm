"""PostgresQueue: the SQS semantics on ``app.queue_messages`` (Supabase pilot)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from bomagent_common.db import platform_transaction
from bomagent_common.messaging import Message, PostgresQueue, Queue, consume_forever, process_one
from bomagent_common.tenancy import TenantContext, current_tenant, tenant_scope

pytestmark = pytest.mark.integration


def _queue(app_engine, platform_engine, **kw) -> PostgresQueue:
    # a unique queue name per test: the table is shared by the whole test session
    return PostgresQueue(
        f"t-{uuid.uuid4().hex[:12]}",
        producer_engine=app_engine,
        consumer_engine=platform_engine,
        poll_interval_s=0.05,
        **kw,
    )


async def _row(platform_engine, queue: PostgresQueue) -> dict:
    async with platform_transaction(platform_engine) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT tenant_id, receive_count, dead_at FROM app.queue_messages"
                    " WHERE queue = :q"
                ),
                {"q": queue.name},
            )
        ).one()
    return dict(row._mapping)


async def test_satisfies_the_queue_protocol(app_engine, platform_engine):
    queue: Queue = _queue(app_engine, platform_engine)
    assert isinstance(queue, PostgresQueue)


async def test_send_receive_ack_round_trip(app_engine, platform_engine, make_tenant):
    tenant = await make_tenant()
    queue = _queue(app_engine, platform_engine)
    msg = Message.create("file.uploaded", tenant, {"file_id": "f1"})
    await queue.send(msg)
    assert (await _row(platform_engine, queue))["tenant_id"] == tenant.tenant_id

    (item,) = await queue.receive(wait_seconds=0)
    assert item.message == msg
    assert await queue.receive(wait_seconds=0) == []  # invisible while in flight
    await queue.ack(item)
    async with platform_transaction(platform_engine) as conn:
        left = await conn.scalar(
            text("SELECT count(*) FROM app.queue_messages WHERE queue = :q"), {"q": queue.name}
        )
    assert left == 0


async def test_unacked_message_reappears_after_visibility_timeout(
    app_engine, platform_engine, make_tenant
):
    tenant = await make_tenant()
    queue = _queue(app_engine, platform_engine, visibility_timeout_s=0.2)
    await queue.send(Message.create("x.y", tenant))
    (first,) = await queue.receive(wait_seconds=0)
    assert await queue.receive(wait_seconds=0) == []
    await asyncio.sleep(0.3)
    (second,) = await queue.receive(wait_seconds=0)
    assert second.message.message_id == first.message.message_id
    assert second.receipt != first.receipt
    assert (await _row(platform_engine, queue))["receive_count"] == 2
    # a stale receipt (the message was re-received meanwhile) does not delete it
    await queue.ack(first)
    assert (await _row(platform_engine, queue))["receive_count"] == 2
    await queue.ack(second)


async def test_dead_lettered_after_max_receives(app_engine, platform_engine, make_tenant):
    tenant = await make_tenant()
    queue = _queue(app_engine, platform_engine, visibility_timeout_s=0.05, max_receive_count=2)
    await queue.send(Message.create("x.y", tenant))

    async def boom(_: Message) -> None:
        raise RuntimeError("fail")

    for _ in range(2):
        (item,) = await queue.receive(wait_seconds=0)
        assert not await process_one(queue, item, boom)
        await asyncio.sleep(0.1)
    assert await queue.receive(wait_seconds=0) == []
    row = await _row(platform_engine, queue)
    assert row["dead_at"] is not None
    assert row["receive_count"] == 2
    assert await queue.dead_letter_count() == 1


async def test_poison_message_is_skipped_and_dead_lettered(
    app_engine, platform_engine, make_tenant, db_urls
):
    from sqlalchemy import create_engine

    tenant = await make_tenant()
    queue = _queue(app_engine, platform_engine, visibility_timeout_s=0.05, max_receive_count=1)
    await queue.send(Message.create("ok", tenant))
    admin = create_engine(db_urls.admin)
    with admin.begin() as conn:  # a row no producer could write through the API
        conn.execute(
            text(
                "INSERT INTO app.queue_messages (id, tenant_id, queue, message)"
                " VALUES (:i, :t, :q, CAST('{\"bad\": true}' AS jsonb))"
            ),
            {"i": uuid.uuid4(), "t": tenant.tenant_id, "q": queue.name},
        )
    admin.dispose()
    items = await queue.receive(wait_seconds=0)
    assert [i.message.type for i in items] == ["ok"]
    await queue.ack(items[0])
    await asyncio.sleep(0.1)
    assert await queue.receive(wait_seconds=0) == []
    assert await queue.dead_letter_count() == 1


async def test_concurrent_consumers_never_get_the_same_message(
    app_engine, platform_engine, make_tenant
):
    tenant = await make_tenant()
    queue = _queue(app_engine, platform_engine)
    for i in range(20):
        await queue.send(Message.create("x.y", tenant, {"i": i}))
    batches = await asyncio.gather(
        *(queue.receive(max_messages=5, wait_seconds=0) for _ in range(6))
    )
    seen = [item.message.payload["i"] for batch in batches for item in batch]
    assert sorted(seen) == list(range(20))  # every message exactly once


async def test_receive_long_polls_until_a_message_arrives(app_engine, platform_engine, make_tenant):
    tenant = await make_tenant()
    queue = _queue(app_engine, platform_engine)

    async def later() -> None:
        await asyncio.sleep(0.2)
        await queue.send(Message.create("late", tenant))

    sender = asyncio.create_task(later())
    items = await queue.receive(wait_seconds=3)
    await sender
    assert [i.message.type for i in items] == ["late"]


async def test_send_refuses_a_message_of_another_active_tenant(
    app_engine, platform_engine, make_tenant
):
    a, b = await make_tenant(), await make_tenant()
    queue = _queue(app_engine, platform_engine)
    with tenant_scope(a), pytest.raises(PermissionError):
        await queue.send(Message.create("x.y", b))


async def test_consume_forever_runs_handlers_in_the_message_tenant(
    app_engine, platform_engine, make_tenant
):
    a, b = await make_tenant(), await make_tenant()
    queue = _queue(app_engine, platform_engine)
    for t in (a, b):
        await queue.send(Message.create("x.y", t))
    seen: list[uuid.UUID] = []
    stop = asyncio.Event()

    async def handler(msg: Message) -> None:
        ctx: TenantContext | None = current_tenant()
        assert ctx is not None
        seen.append(ctx.tenant_id)
        if len(seen) == 2:
            stop.set()

    await asyncio.wait_for(consume_forever(queue, handler, stop=stop, wait_seconds=1), timeout=10)
    assert sorted(seen) == sorted([a.tenant_id, b.tenant_id])


async def test_purge_dead_removes_old_dead_letters(app_engine, platform_engine, make_tenant):
    tenant = await make_tenant()
    queue = _queue(app_engine, platform_engine, visibility_timeout_s=0.01, max_receive_count=1)
    await queue.send(Message.create("x.y", tenant))
    await queue.receive(wait_seconds=0)
    await asyncio.sleep(0.05)
    assert await queue.receive(wait_seconds=0) == []
    assert await queue.purge_dead(older_than_s=3600) == 0
    assert await queue.purge_dead(older_than_s=0) == 1
    assert await queue.dead_letter_count() == 0


def test_requires_the_engine_for_each_side():
    queue = PostgresQueue("runs")
    with pytest.raises(RuntimeError, match="producer"):
        asyncio.run(queue.send(Message.create("x", TenantContext(uuid.uuid4(), "u"))))
    with pytest.raises(RuntimeError, match="consumer"):
        asyncio.run(queue.receive(wait_seconds=0))


def test_rejects_invalid_queue_names():
    with pytest.raises(ValueError, match="queue name"):
        PostgresQueue("Runs; DROP TABLE x")
