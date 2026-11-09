"""Queue messages carrying tenant and trace context (ARCHITECTURE.md §5, §11).

Every message has ``tenant_id``; workers restore :class:`TenantContext` and the W3C trace
context before touching data. Two transports: Amazon SQS (moto locally) and in-memory
(unit tests). Failed messages are not acknowledged, so SQS redrives them to the DLQ after
``maxReceiveCount`` attempts.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from pydantic import BaseModel, Field

from bomagent_common.logging import get_logger
from bomagent_common.tenancy import TenantContext, tenant_scope

log = get_logger(__name__)
tracer = trace.get_tracer(__name__)


class Message(BaseModel):
    """Envelope for all asynchronous work."""

    message_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    type: str
    tenant_id: uuid.UUID
    actor_id: str
    actor_type: str = "service"
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trace_carrier: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def create(
        cls, type_: str, ctx: TenantContext, payload: dict[str, Any] | None = None
    ) -> Message:
        carrier: dict[str, str] = {}
        inject(carrier)
        return cls(
            type=type_,
            tenant_id=ctx.tenant_id,
            actor_id=ctx.actor_id,
            actor_type=ctx.actor_type,
            payload=payload or {},
            trace_carrier=carrier,
        )

    def tenant_context(self) -> TenantContext:
        return TenantContext(
            tenant_id=self.tenant_id, actor_id=self.actor_id, actor_type=self.actor_type
        )


@dataclass(frozen=True, slots=True)
class Received:
    message: Message
    receipt: str


class Queue(Protocol):
    async def send(self, message: Message) -> None: ...
    async def receive(
        self, *, max_messages: int = 10, wait_seconds: int = 10
    ) -> list[Received]: ...
    async def ack(self, received: Received) -> None: ...


class InMemoryQueue:
    """Process-local queue for tests; mirrors SQS at-least-once semantics."""

    def __init__(self, max_receive_count: int = 3) -> None:
        self._items: deque[Message] = deque()
        self._inflight: dict[str, Message] = {}
        self._receives: defaultdict[uuid.UUID, int] = defaultdict(int)
        self.dead_letters: list[Message] = []
        self._max_receive = max_receive_count

    async def send(self, message: Message) -> None:
        self._items.append(message)

    async def receive(self, *, max_messages: int = 10, wait_seconds: int = 0) -> list[Received]:
        out: list[Received] = []
        while self._items and len(out) < max_messages:
            msg = self._items.popleft()
            self._receives[msg.message_id] += 1
            receipt = str(uuid.uuid4())
            self._inflight[receipt] = msg
            out.append(Received(msg, receipt))
        return out

    async def ack(self, received: Received) -> None:
        self._inflight.pop(received.receipt, None)

    def nack_all(self) -> None:
        """Simulate visibility timeout expiry of unacknowledged messages."""
        for receipt, msg in list(self._inflight.items()):
            del self._inflight[receipt]
            if self._receives[msg.message_id] >= self._max_receive:
                self.dead_letters.append(msg)
            else:
                self._items.append(msg)

    def __len__(self) -> int:
        return len(self._items)


class SqsQueue:
    """Amazon SQS transport (boto3 in a thread; works against moto locally)."""

    def __init__(self, queue_url: str, *, region: str, endpoint_url: str | None = None) -> None:
        import boto3

        self._url = queue_url
        self._client = boto3.client("sqs", region_name=region, endpoint_url=endpoint_url)

    async def send(self, message: Message) -> None:
        await asyncio.to_thread(
            self._client.send_message,
            QueueUrl=self._url,
            MessageBody=message.model_dump_json(),
            MessageAttributes={
                "tenant_id": {"DataType": "String", "StringValue": str(message.tenant_id)},
                "type": {"DataType": "String", "StringValue": message.type},
            },
        )

    async def receive(self, *, max_messages: int = 10, wait_seconds: int = 10) -> list[Received]:
        resp = await asyncio.to_thread(
            self._client.receive_message,
            QueueUrl=self._url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        return [
            Received(Message.model_validate_json(m["Body"]), m["ReceiptHandle"])
            for m in resp.get("Messages", [])
        ]

    async def ack(self, received: Received) -> None:
        await asyncio.to_thread(
            self._client.delete_message, QueueUrl=self._url, ReceiptHandle=received.receipt
        )


Handler = Callable[[Message], Awaitable[None]]


async def process_one(queue: Queue, received: Received, handler: Handler) -> bool:
    """Run ``handler`` in the message's tenant + trace context; ack only on success."""
    msg = received.message
    token = otel_context.attach(extract(msg.trace_carrier))
    try:
        with (
            tracer.start_as_current_span(
                f"process {msg.type}",
                kind=trace.SpanKind.CONSUMER,
                attributes={
                    "messaging.message.id": str(msg.message_id),
                    "messaging.operation.type": "process",
                    "tenant.id": str(msg.tenant_id),
                },
            ) as span,
            tenant_scope(msg.tenant_context()),
        ):
            try:
                await handler(msg)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, type(exc).__name__)
                log.warning("message_failed", message_type=msg.type, error=type(exc).__name__)
                return False
        await queue.ack(received)
        return True
    finally:
        otel_context.detach(token)


async def consume_forever(
    queue: Queue, handler: Handler, *, stop: asyncio.Event, wait_seconds: int = 10
) -> None:
    """Long-poll loop used by workers (cancel via ``stop``)."""
    while not stop.is_set():
        try:
            batch = await queue.receive(wait_seconds=wait_seconds)
        except Exception:
            log.exception("queue_receive_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=2)
            continue
        for item in batch:
            await process_one(queue, item, handler)
        if not batch:
            await asyncio.sleep(0)
