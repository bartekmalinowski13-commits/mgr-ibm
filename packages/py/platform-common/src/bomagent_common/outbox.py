"""Transactional outbox for queue messages (``app.outbox``, RLS per tenant).

``enqueue`` inside the business transaction; ``deliver`` after commit (best effort) and
periodically from a relay for whatever is still pending.
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
) -> int:
    """Send pending messages of one tenant; returns how many were sent. Rows are locked
    with SKIP LOCKED, so concurrent relays never send the same row at the same time."""
    sent = 0
    filters = " AND id = ANY(:ids)" if ids is not None else ""
    async with tenant_transaction(engine, tenant_id) as conn:
        rows = await conn.execute(
            text(
                "SELECT id, queue, message FROM app.outbox WHERE sent_at IS NULL"  # noqa: S608
                " AND tenant_id = app.current_tenant_id()"
                f" AND created_at <= now() - make_interval(secs => :age){filters}"
                " ORDER BY created_at LIMIT :n FOR UPDATE SKIP LOCKED"
            ),
            {"age": older_than_s, "n": batch, **({"ids": list(ids)} if ids is not None else {})},
        )
        for row in rows.all():
            try:
                await queues[row.queue].send(Message.model_validate(row.message))
            except Exception as exc:
                log.warning("outbox_send_failed", outbox_id=str(row.id), error=type(exc).__name__)
                await conn.execute(
                    text(
                        "UPDATE app.outbox SET attempts = attempts + 1, last_error = :e"
                        " WHERE id = :i"
                    ),
                    {"e": type(exc).__name__, "i": row.id},
                )
                continue
            await conn.execute(
                text(
                    "UPDATE app.outbox SET sent_at = now(), attempts = attempts + 1 WHERE id = :i"
                ),
                {"i": row.id},
            )
            sent += 1
    return sent
