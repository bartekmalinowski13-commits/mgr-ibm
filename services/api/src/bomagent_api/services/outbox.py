"""Post-commit delivery of outbox messages, shared by every use case that enqueues one."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_common.logging import get_logger
from bomagent_common.messaging import Queue
from bomagent_common.outbox import deliver

log = get_logger(__name__)


async def deliver_now(
    engine: AsyncEngine, queues: Mapping[str, Queue], tenant_id: uuid.UUID, outbox_id: uuid.UUID
) -> None:
    """Send a committed outbox message right away; on failure the relay retries it."""
    try:
        await deliver(engine, tenant_id, queues, ids=[outbox_id])
    except Exception:
        log.warning("outbox_deliver_deferred", outbox_id=str(outbox_id))
