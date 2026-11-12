"""Transactional outbox for queue messages (``app.outbox``, RLS per tenant).

``enqueue`` inside the business transaction; ``deliver`` after commit (best effort) and
periodically from a relay for whatever is still pending. A row whose delivery failed
``MAX_ATTEMPTS`` times and that is older than ``GIVE_UP_AFTER_S`` is marked dead
(``dead_at``, with ``last_error``) and no longer retried; sent rows are deleted after a
retention period (``cleanup_sent``).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.messaging import Message, Queue

log = get_logger(__name__)
MAX_ATTEMPTS = 10
#: a row is given up only when it failed MAX_ATTEMPTS times *and* is older than this, so a
#: short SQS outage swept by several API replicas does not dead-letter fresh messages
GIVE_UP_AFTER_S = 24 * 3600
SENT_RETENTION_DAYS = 7


async def enqueue(conn: AsyncConnection, queue: str, message: Message) -> uuid.UUID:
    oid = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO app.outbox (id, tenant_id, queue, message)"
            " VALUES (:i, app.current_tenant_id(), :q, CAST(:m AS jsonb))"
        ),
        {"i": oid, "q": queue, "m": message.model_dump_json()},
    )
    return oid


async def deliver(
    engine: AsyncEngine,
    tenant_id: uuid.UUID,
    queues: Mapping[str, Queue],
    *,
    ids: Sequence[uuid.UUID] | None = None,
    older_than_s: float = 0.0,
    batch: int = 100,
    max_attempts: int = MAX_ATTEMPTS,
    give_up_after_s: float = GIVE_UP_AFTER_S,
) -> int:
    """Send pending messages of one tenant; returns how many were sent. Rows are locked
    with SKIP LOCKED, so concurrent relays never send the same row at the same time."""
    sent = 0
    filters = " AND id = ANY(:ids)" if ids is not None else ""
    async with tenant_transaction(engine, tenant_id) as conn:
        rows = await conn.execute(
            text(
                "SELECT id, queue, message FROM app.outbox"  # noqa: S608
                " WHERE sent_at IS NULL AND dead_at IS NULL"
                " AND tenant_id = app.current_tenant_id()"
                f" AND created_at <= now() - make_interval(secs => :age){filters}"
                " ORDER BY created_at LIMIT :n FOR UPDATE SKIP LOCKED"
            ),
            {"age": older_than_s, "n": batch, **({"ids": list(ids)} if ids is not None else {})},
        )
        for row in rows.all():
            try:
                await queues[row.queue].send(_envelope(row.message, tenant_id))
            except Exception as exc:
                error = type(exc).__name__
                dead = (
                    await conn.execute(
                        text(
                            "UPDATE app.outbox SET attempts = attempts + 1, last_error = :e,"
                            " dead_at = CASE WHEN attempts + 1 >= :max AND created_at <"
                            " now() - make_interval(secs => :ttl) THEN now() END"
                            " WHERE id = :i RETURNING dead_at IS NOT NULL"
                        ),
                        {"e": error, "i": row.id, "max": max_attempts, "ttl": give_up_after_s},
                    )
                ).scalar()
                if dead:
                    log.error(  # noqa: TRY400
                        "outbox_message_dead",
                        outbox_id=str(row.id),
                        queue=row.queue,
                        error=error,
                        attempts=max_attempts,
                    )
                else:
                    log.warning("outbox_send_failed", outbox_id=str(row.id), error=error)
                continue
            await conn.execute(
                text(
                    "UPDATE app.outbox SET sent_at = now(), attempts = attempts + 1 WHERE id = :i"
                ),
                {"i": row.id},
            )
            sent += 1
    return sent


def _envelope(raw: object, tenant_id: uuid.UUID) -> Message:
    """The stored message, refused when it names another tenant (consumers act on the
    envelope's tenant, RLS only checked the row's)."""
    message = Message.model_validate(raw)
    if message.tenant_id != tenant_id:
        raise ValueError("outbox message names another tenant")
    return message


async def cleanup_sent(
    engine: AsyncEngine, tenant_id: uuid.UUID, *, older_than_days: int = SENT_RETENTION_DAYS
) -> int:
    """Delete rows of one tenant that were sent more than ``older_than_days`` ago."""
    async with tenant_transaction(engine, tenant_id) as conn:
        result = await conn.execute(
            text(
                "DELETE FROM app.outbox WHERE tenant_id = app.current_tenant_id()"
                " AND sent_at < now() - make_interval(days => :d)"
            ),
            {"d": older_than_days},
        )
    return int(result.rowcount)
