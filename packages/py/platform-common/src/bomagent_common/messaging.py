"""Queue messages carrying tenant and trace context (ARCHITECTURE.md §5, §11).

Every message has ``tenant_id``; workers restore :class:`TenantContext` and the W3C trace
context before touching data. Three transports: Amazon SQS (AWS; moto locally), a
PostgreSQL table (``PostgresQueue``, the Supabase pilot deployment without SQS) and
in-memory (unit tests). Failed messages are not acknowledged, so they are redelivered after
the visibility timeout and dead-lettered after ``maxReceiveCount`` receives.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from pydantic import BaseModel, Field
from sqlalchemy import text

from bomagent_common.db import make_engine, platform_transaction, tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.tenancy import TenantContext, current_tenant, tenant_scope

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from bomagent_common.config import ServiceSettings

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
        out: list[Received] = []
        for m in resp.get("Messages", []):
            try:
                out.append(Received(Message.model_validate_json(m["Body"]), m["ReceiptHandle"]))
            except ValueError:
                # poison message: leave it unacknowledged so SQS redrives it to the DLQ;
                # never let it block valid messages of other tenants in the same batch
                log.warning("message_invalid", message_id=m.get("MessageId", "?"))
        return out

    async def ack(self, received: Received) -> None:
        await asyncio.to_thread(
            self._client.delete_message, QueueUrl=self._url, ReceiptHandle=received.receipt
        )


_QUEUE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")


class PostgresQueue:
    """Queue in ``app.queue_messages`` (migration 0013) with SQS semantics.

    * ``send`` runs with the **producer** engine (``bomagent_app``) in the message's
      tenant context: RLS lets the app role insert rows of that tenant only.
    * ``receive``/``ack`` run with the **consumer** engine (``bomagent_platform``), which
      may read and update the delivery bookkeeping across tenants (explicit policies in
      0013, no BYPASSRLS); handlers then work in the message's tenant (``process_one``).
    * A received message is invisible for ``visibility_timeout_s`` and comes back unless
      it is acknowledged; once it was received ``max_receive_count`` times and is visible
      again, it is dead-lettered (``dead_at``) instead of delivered, like an SQS redrive.
    * Rows are claimed with ``FOR UPDATE SKIP LOCKED``: concurrent consumers (threads,
      processes, machines) never receive the same message at the same time.
    * ``receive(wait_seconds=...)`` long-polls by re-querying every ``poll_interval_s``.
    """

    def __init__(
        self,
        name: str,
        *,
        producer_engine: AsyncEngine | None = None,
        consumer_engine: AsyncEngine | None = None,
        visibility_timeout_s: float = 900.0,
        max_receive_count: int = 5,
        poll_interval_s: float = 1.0,
    ) -> None:
        if not _QUEUE_NAME.fullmatch(name):
            raise ValueError(f"invalid queue name {name!r}")
        self.name = name
        self._producer = producer_engine
        self._consumer = consumer_engine
        self._visibility = visibility_timeout_s
        self._max_receive = max_receive_count
        self._poll = poll_interval_s

    def _engine(self, side: str) -> AsyncEngine:
        engine = self._producer if side == "producer" else self._consumer
        if engine is None:
            raise RuntimeError(f"PostgresQueue {self.name!r} has no {side} engine")
        return engine

    async def send(self, message: Message) -> None:
        active = current_tenant()
        if active is not None and active.tenant_id != message.tenant_id:
            raise PermissionError("message belongs to another tenant than the active context")
        async with tenant_transaction(self._engine("producer"), message.tenant_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO app.queue_messages (id, tenant_id, queue, message)"
                    " VALUES (:i, :t, :q, CAST(:m AS jsonb))"
                ),
                {
                    "i": uuid.uuid4(),
                    "t": message.tenant_id,
                    "q": self.name,
                    "m": message.model_dump_json(),
                },
            )

    async def _receive_once(self, max_messages: int) -> list[Received]:
        async with platform_transaction(self._engine("consumer")) as conn:
            dead = await conn.execute(
                text(
                    "UPDATE app.queue_messages SET dead_at = now() WHERE id IN ("
                    " SELECT id FROM app.queue_messages WHERE queue = :q AND dead_at IS NULL"
                    " AND visible_at <= now() AND receive_count >= :max"
                    " FOR UPDATE SKIP LOCKED) RETURNING id"
                ),
                {"q": self.name, "max": self._max_receive},
            )
            for row_id in dead.scalars():
                log.error("queue_message_dead", queue=self.name, queue_message_id=str(row_id))
            rows = (
                await conn.execute(
                    text(
                        "WITH picked AS ("
                        " SELECT id FROM app.queue_messages WHERE queue = :q"
                        " AND dead_at IS NULL AND visible_at <= now()"
                        " ORDER BY visible_at, enqueued_at LIMIT :n FOR UPDATE SKIP LOCKED)"
                        " UPDATE app.queue_messages m SET receive_count = m.receive_count + 1,"
                        " visible_at = clock_timestamp() + make_interval(secs => :vt),"
                        " receipt = gen_random_uuid()"
                        " FROM picked WHERE m.id = picked.id"
                        " RETURNING m.id, m.receipt, m.message, m.visible_at"
                    ),
                    {"q": self.name, "n": max_messages, "vt": self._visibility},
                )
            ).all()
        out: list[Received] = []
        for row in sorted(rows, key=lambda r: r.visible_at):
            try:
                message = Message.model_validate(row.message)
            except ValueError:
                # poison message: never acknowledged, so it is dead-lettered after
                # max_receive_count receives; it never blocks other messages of the batch
                log.warning("message_invalid", queue_message_id=str(row.id))
                continue
            out.append(Received(message, f"{row.id}:{row.receipt}"))
        return out

    async def receive(self, *, max_messages: int = 10, wait_seconds: int = 10) -> list[Received]:
        deadline = time.monotonic() + max(wait_seconds, 0)
        while True:
            out = await self._receive_once(max_messages)
            if out or time.monotonic() >= deadline:
                return out
            await asyncio.sleep(min(self._poll, max(deadline - time.monotonic(), 0)))

    async def ack(self, received: Received) -> None:
        """Delete the message - only while ``received`` is its latest delivery (a stale
        receipt after the visibility timeout expired and another consumer took the
        message leaves it alone, as SQS does for an expired receipt handle)."""
        row_id, receipt = received.receipt.split(":", 1)
        async with platform_transaction(self._engine("consumer")) as conn:
            await conn.execute(
                text("DELETE FROM app.queue_messages WHERE id = :i AND receipt = :r"),
                {"i": uuid.UUID(row_id), "r": uuid.UUID(receipt)},
            )

    async def dead_letter_count(self) -> int:
        async with platform_transaction(self._engine("consumer")) as conn:
            count = await conn.scalar(
                text(
                    "SELECT count(*) FROM app.queue_messages"
                    " WHERE queue = :q AND dead_at IS NOT NULL"
                ),
                {"q": self.name},
            )
        return int(count or 0)

    async def purge_dead(self, *, older_than_s: float = 14 * 24 * 3600) -> int:
        """Delete dead letters older than ``older_than_s`` (default 14 days, like the
        SQS dead-letter queues' retention in AWS)."""
        async with platform_transaction(self._engine("consumer")) as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM app.queue_messages WHERE queue = :q AND dead_at IS NOT NULL"
                    " AND dead_at <= now() - make_interval(secs => :age)"
                ),
                {"q": self.name, "age": older_than_s},
            )
        return int(result.rowcount)


#: same visibility timeouts and redrive count as the SQS queues in AWS (infra data stack)
QUEUE_VISIBILITY_S: dict[str, float] = {"ingest": 600.0, "runs": 3600.0, "kb": 900.0}
MAX_RECEIVE_COUNT = 5


def make_queue(
    settings: ServiceSettings,
    name: str,
    *,
    sqs_url: str | None,
    producer_engine: AsyncEngine | None = None,
    consumer_engine: AsyncEngine | None = None,
) -> Queue | None:
    """The queue ``name`` for ``settings.queue_backend``: SQS (``sqs_url``; ``None`` when
    unset) or ``PostgresQueue`` (producer = app role engine, consumer = platform role)."""
    if settings.queue_backend == "postgres":
        return PostgresQueue(
            name,
            producer_engine=producer_engine,
            consumer_engine=consumer_engine,
            visibility_timeout_s=QUEUE_VISIBILITY_S.get(name, 900.0),
            max_receive_count=MAX_RECEIVE_COUNT,
            poll_interval_s=settings.queue_poll_interval_s,
        )
    if sqs_url:
        return SqsQueue(sqs_url, region=settings.aws_region, endpoint_url=settings.aws_endpoint_url)
    return None


def consumer_queue(settings: ServiceSettings, name: str, *, sqs_url: str | None) -> Queue | None:
    """The queue a worker consumes; ``None`` (health-only mode) when nothing is configured.
    The postgres backend consumes with the platform role (``platform_database_url``)."""
    consumer: AsyncEngine | None = None
    if settings.queue_backend == "postgres":
        if not settings.platform_database_url:
            raise RuntimeError(
                "BOMAGENT_PLATFORM_DATABASE_URL (or BOMAGENT_PLATFORM_DATABASE_PASSWORD) is"
                " required to consume the postgres queue"
            )
        consumer = make_engine(settings.platform_database_url, pool_size=2)
    return make_queue(settings, name, sqs_url=sqs_url, consumer_engine=consumer)


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
    queue: Queue,
    handler: Handler,
    *,
    stop: asyncio.Event,
    wait_seconds: int = 10,
    max_messages: int = 10,
) -> None:
    """Long-poll loop used by workers (cancel via ``stop``). Slow handlers pass
    ``max_messages=1``: messages of a batch wait unprocessed while earlier ones run, and
    must not outlive the queue's visibility timeout."""
    while not stop.is_set():
        try:
            batch = await queue.receive(wait_seconds=wait_seconds, max_messages=max_messages)
        except Exception:
            log.exception("queue_receive_failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=2)
            continue
        for item in batch:
            await process_one(queue, item, handler)
        if not batch:
            await asyncio.sleep(0)
