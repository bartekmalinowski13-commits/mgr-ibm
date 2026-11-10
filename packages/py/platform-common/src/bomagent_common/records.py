"""Persistence of projects, designs and runs (migration 0003).

Plain SQL on a connection opened with ``tenant_transaction``: every statement is subject
to RLS, so a row of another tenant is simply invisible (``None``), never an error that
would reveal its existence. Shared by the API and the workers.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Row = dict[str, Any]


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps([created_at.isoformat(), str(row_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        ts, rid = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(ts), uuid.UUID(rid)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid cursor") from exc


async def _one(conn: AsyncConnection, sql: str, params: dict[str, Any]) -> Row | None:
    row = (await conn.execute(text(sql), params)).mappings().first()
    return dict(row) if row is not None else None


async def _page(
    conn: AsyncConnection,
    table: str,
    where: str,
    params: dict[str, Any],
    limit: int,
    cursor: str | None,
) -> tuple[list[Row], str | None]:
    if cursor:
        ts, rid = decode_cursor(cursor)
        where += " AND (created_at, id) < (:c_ts, :c_id)"
        params = params | {"c_ts": ts, "c_id": rid}
    rows = (
        (
            await conn.execute(
                text(  # table/where are module constants, values are bound parameters
                    f"SELECT * FROM {table} WHERE {where} "  # noqa: S608
                    "ORDER BY created_at DESC, id DESC LIMIT :lim"
                ),
                params | {"lim": limit + 1},
            )
        )
        .mappings()
        .all()
    )
    items = [dict(r) for r in rows[:limit]]
    nxt = encode_cursor(items[-1]["created_at"], items[-1]["id"]) if len(rows) > limit else None
    return items, nxt


# ------------------------------------------------------------------ projects
async def insert_project(
    conn: AsyncConnection, tenant_id: uuid.UUID, name: str, created_by: str
) -> Row:
    row = await _one(
        conn,
        """INSERT INTO app.projects (id, tenant_id, name, created_by)
           VALUES (:id, :tenant_id, :name, :by) RETURNING *""",
        {"id": uuid.uuid4(), "tenant_id": tenant_id, "name": name, "by": created_by},
    )
    if row is None:  # pragma: no cover - INSERT ... RETURNING always yields a row
        raise RuntimeError("insert returned no row")
    return row


async def get_project(conn: AsyncConnection, project_id: uuid.UUID) -> Row | None:
    return await _one(conn, "SELECT * FROM app.projects WHERE id = :id", {"id": project_id})


async def list_projects(
    conn: AsyncConnection, limit: int, cursor: str | None
) -> tuple[list[Row], str | None]:
    return await _page(conn, "app.projects", "true", {}, limit, cursor)


# ------------------------------------------------------------------ designs
async def insert_design(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    filenames: list[str],
    created_by: str,
) -> Row:
    row = await _one(
        conn,
        """INSERT INTO app.designs (id, tenant_id, project_id, filenames, created_by)
           VALUES (:id, :tenant_id, :project_id, :filenames, :by) RETURNING *""",
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "project_id": project_id,
            "filenames": filenames,
            "by": created_by,
        },
    )
    if row is None:  # pragma: no cover - INSERT ... RETURNING always yields a row
        raise RuntimeError("insert returned no row")
    return row


async def get_design(conn: AsyncConnection, design_id: uuid.UUID) -> Row | None:
    return await _one(conn, "SELECT * FROM app.designs WHERE id = :id", {"id": design_id})


async def set_design_status(
    conn: AsyncConnection,
    design_id: uuid.UUID,
    status: str,
    *,
    expected: tuple[str, ...] | None = None,
    **fields: Any,
) -> Row | None:
    """Status transition; ``expected`` guards against out-of-order messages."""
    sets = ["status = :status", "updated_at = now()"]
    params: dict[str, Any] = {"id": design_id, "status": status}
    for key in ("source_format", "components", "confidence", "parsed_key", "error"):
        if key in fields:
            sets.append(f"{key} = :{key}")
            params[key] = fields[key]
    if "limitations" in fields:
        sets.append("limitations = CAST(:limitations AS jsonb)")
        params["limitations"] = json.dumps(fields["limitations"])
    guard = ""
    if expected:
        guard = " AND status = ANY(:expected)"
        params["expected"] = list(expected)
    return await _one(
        conn,
        f"UPDATE app.designs SET {', '.join(sets)} WHERE id = :id{guard} RETURNING *",  # noqa: S608
        params,
    )


# ------------------------------------------------------------------ runs
async def insert_run(
    conn: AsyncConnection,
    *,
    tenant_id: uuid.UUID,
    design_id: uuid.UUID,
    variant: str,
    model_id: str,
    idempotency_key: str,
    requirements: dict[str, Any],
    budget: dict[str, Any] | None,
    created_by: str,
) -> tuple[Row, bool]:
    """Insert a run or return the existing one for the same idempotency key.
    Returns ``(row, created)``."""
    row = await _one(
        conn,
        """INSERT INTO app.runs (id, tenant_id, design_id, variant, model_id, idempotency_key,
                                 requirements, budget, created_by)
           VALUES (:id, :tenant_id, :design_id, :variant, :model_id, :key,
                   CAST(:requirements AS jsonb), CAST(:budget AS jsonb), :by)
           ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
           RETURNING *""",
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "design_id": design_id,
            "variant": variant,
            "model_id": model_id,
            "key": idempotency_key,
            "requirements": json.dumps(requirements),
            "budget": json.dumps(budget) if budget is not None else None,
            "by": created_by,
        },
    )
    if row is not None:
        return row, True
    existing = await _one(
        conn, "SELECT * FROM app.runs WHERE idempotency_key = :key", {"key": idempotency_key}
    )
    if existing is None:  # pragma: no cover - conflict implies the row exists
        raise RuntimeError("idempotent run lookup failed")
    return existing, False


async def get_run(conn: AsyncConnection, run_id: uuid.UUID) -> Row | None:
    return await _one(conn, "SELECT * FROM app.runs WHERE id = :id", {"id": run_id})


async def list_runs(
    conn: AsyncConnection, limit: int, cursor: str | None
) -> tuple[list[Row], str | None]:
    return await _page(conn, "app.runs", "true", {}, limit, cursor)


async def mark_run_running(conn: AsyncConnection, run_id: uuid.UUID) -> Row | None:
    return await _one(
        conn,
        """UPDATE app.runs SET status = 'running', started_at = now()
           WHERE id = :id AND status IN ('queued', 'running') RETURNING *""",
        {"id": run_id},
    )


async def mark_run_finished(
    conn: AsyncConnection,
    run_id: uuid.UUID,
    *,
    status: str,
    bom_key: str | None,
    result_key: str | None,
    usage: dict[str, Any] | None,
    error: str | None,
) -> Row | None:
    return await _one(
        conn,
        """UPDATE app.runs SET status = :status, bom_key = :bom_key, result_key = :result_key,
                  usage = CAST(:usage AS jsonb), error = :error, finished_at = now()
           WHERE id = :id AND status IN ('queued', 'running') RETURNING *""",
        {
            "id": run_id,
            "status": status,
            "bom_key": bom_key,
            "result_key": result_key,
            "usage": json.dumps(usage) if usage is not None else None,
            "error": error,
        },
    )
