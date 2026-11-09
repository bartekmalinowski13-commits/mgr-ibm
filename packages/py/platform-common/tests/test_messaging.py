from __future__ import annotations

import asyncio
import uuid

import boto3
import pytest
from moto import mock_aws

from bomagent_common.messaging import (
    InMemoryQueue,
    Message,
    SqsQueue,
    consume_forever,
    process_one,
)
from bomagent_common.tenancy import TenantContext, current_tenant


@pytest.fixture
def ctx() -> TenantContext:
    return TenantContext(tenant_id=uuid.uuid4(), actor_id="user-1", actor_type="user")


async def test_handler_runs_in_message_tenant_context(ctx):
    queue = InMemoryQueue()
    await queue.send(Message.create("run.requested", ctx, {"run_id": "r1"}))
    seen: list[uuid.UUID] = []

    async def handler(msg: Message) -> None:
        tenant = current_tenant()
        assert tenant is not None
        seen.append(tenant.tenant_id)

    (item,) = await queue.receive()
    assert await process_one(queue, item, handler)
    assert seen == [ctx.tenant_id]
    assert current_tenant() is None


async def test_failed_message_is_retried_then_dead_lettered(ctx):
    queue = InMemoryQueue(max_receive_count=2)
    await queue.send(Message.create("run.requested", ctx))

    async def boom(_: Message) -> None:
        raise RuntimeError("fail")

    for _ in range(2):
        (item,) = await queue.receive()
        assert not await process_one(queue, item, boom)
        queue.nack_all()
    assert len(queue) == 0
    assert len(queue.dead_letters) == 1


async def test_consume_forever_stops_on_event(ctx):
    queue = InMemoryQueue()
    for i in range(3):
        await queue.send(Message.create("x.y", ctx, {"i": i}))
    stop = asyncio.Event()
    handled: list[int] = []

    async def handler(msg: Message) -> None:
        handled.append(msg.payload["i"])
        if len(handled) == 3:
            stop.set()

    await asyncio.wait_for(consume_forever(queue, handler, stop=stop, wait_seconds=0), timeout=5)
    assert handled == [0, 1, 2]


async def test_sqs_roundtrip_with_moto(ctx, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        url = boto3.client("sqs", region_name="eu-central-1").create_queue(QueueName="runs")[
            "QueueUrl"
        ]
        queue = SqsQueue(url, region="eu-central-1")
        await queue.send(Message.create("run.requested", ctx, {"run_id": "r1"}))
        items = await queue.receive(wait_seconds=0)
        assert len(items) == 1
        assert items[0].message.tenant_id == ctx.tenant_id
        await queue.ack(items[0])
        assert await queue.receive(wait_seconds=0) == []


async def test_poison_sqs_message_does_not_block_batch(ctx, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("sqs", region_name="eu-central-1")
        url = client.create_queue(QueueName="runs")["QueueUrl"]
        client.send_message(QueueUrl=url, MessageBody="{not json")
        queue = SqsQueue(url, region="eu-central-1")
        await queue.send(Message.create("run.requested", ctx))
        items = await queue.receive(wait_seconds=0)
        assert [i.message.type for i in items] == ["run.requested"]
