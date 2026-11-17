"""SQL of the audit log (``audit.events``; reads only, writes go through ``emit_audit``)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def list_events(
    conn: AsyncConnection,
    *,
    cursor: str | None,
    limit: int,
    object_type: str | None,
    actor_id: str | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"lim": limit}
    where = ""
    if cursor:
        where += " AND seq < :c"
        params["c"] = int(cursor) if cursor.isdigit() else 0
    if object_type:
        where += " AND object_type = :ot"
        params["ot"] = object_type
    if actor_id:
        where += " AND actor_id = :a"
        params["a"] = actor_id
    cols = "seq, occurred_at, actor_type, actor_id, action, object_type, object_id, before, after"
    # S608: ``cols`` is a fixed list and ``where`` is assembled from constant clauses above
    # (identifiers from a fixed whitelist, never user input); every value is a bound parameter
    sql = f"SELECT {cols} FROM audit.events WHERE true{where} ORDER BY seq DESC LIMIT :lim"  # noqa: S608
    return [dict(r._mapping) for r in await conn.execute(text(sql), params)]


async def count_events_last_24h(conn: AsyncConnection, action: str) -> int:
    """How many events of an action were recorded in the last 24 hours."""
    return int(
        (
            await conn.execute(
                text(
                    "SELECT count(*) FROM audit.events WHERE action = :a"
                    " AND occurred_at > now() - interval '24 hours'"
                ),
                {"a": action},
            )
        ).scalar()
        or 0
    )
