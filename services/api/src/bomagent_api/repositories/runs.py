"""SQL of runs (``runs.runs``) and their BOM versions (``bom.versions``)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import ColumnElement, Text, cast, func, insert, literal, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_api.repositories.tables import bom_versions, runs

_RUN_COLS = (
    runs.c.id,
    runs.c.project_id,
    runs.c.variant,
    runs.c.runtime,
    runs.c.model_id,
    runs.c.status,
    runs.c.usage,
    runs.c.error,
    runs.c.created_by,
    runs.c.created_at,
    runs.c.started_at,
    runs.c.finished_at,
    runs.c.kb_snapshot_id,
)


async def get(conn: AsyncConnection, run_id: uuid.UUID) -> dict[str, Any] | None:
    row = (await conn.execute(select(*_RUN_COLS).where(runs.c.id == run_id))).first()
    return dict(row._mapping) if row is not None else None


async def list_page(
    conn: AsyncConnection,
    *,
    after: ColumnElement[bool] | None,
    project_id: uuid.UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = select(*_RUN_COLS)
    if project_id is not None:
        stmt = stmt.where(runs.c.project_id == project_id)
    if after is not None:
        stmt = stmt.where(after)
    stmt = stmt.order_by(runs.c.created_at.desc(), runs.c.id.desc()).limit(limit)
    return [dict(r._mapping) for r in await conn.execute(stmt)]


async def has_active_run(conn: AsyncConnection, project_id: uuid.UUID) -> bool:
    """A queued or running run holds the object keys of the project's files."""
    row = (
        await conn.execute(
            select(1)
            .where(runs.c.project_id == project_id, runs.c.status.in_(("queued", "running")))
            .limit(1)
        )
    ).first()
    return row is not None


async def get_for_rerun(conn: AsyncConnection, run_id: uuid.UUID) -> Any | None:
    return (
        await conn.execute(
            select(
                runs.c.project_id,
                runs.c.variant,
                runs.c.runtime,
                runs.c.model_id,
                runs.c.requirements,
            ).where(runs.c.id == run_id)
        )
    ).first()


async def insert_run(
    conn: AsyncConnection,
    *,
    run_id: uuid.UUID,
    project_id: uuid.UUID,
    variant: str,
    runtime: str,
    model_id: str,
    requirements: dict[str, Any],
    kb_snapshot_id: str | None,
    created_by: str,
) -> None:
    await conn.execute(
        insert(runs).values(
            id=run_id,
            tenant_id=func.app.current_tenant_id(),
            project_id=project_id,
            variant=variant,
            runtime=runtime,
            model_id=model_id,
            requirements=cast(literal(json.dumps(requirements), Text), JSONB),
            kb_snapshot_id=kb_snapshot_id,
            created_by=created_by,
        )
    )


async def lock_status(conn: AsyncConnection, run_id: uuid.UUID) -> Any | None:
    return (
        await conn.execute(select(runs.c.status).where(runs.c.id == run_id).with_for_update())
    ).first()


async def lock_run(conn: AsyncConnection, run_id: uuid.UUID) -> None:
    """Serialise writers of one run (edits of its BOM race for the next version)."""
    await conn.execute(select(1).where(runs.c.id == run_id).with_for_update())


async def mark_failed(conn: AsyncConnection, run_id: uuid.UUID, error: str) -> None:
    await conn.execute(
        update(runs)
        .where(runs.c.id == run_id)
        .values(status="failed", error=error, finished_at=func.now())
    )


async def trace_of(conn: AsyncConnection, run_id: uuid.UUID) -> Any | None:
    return (await conn.execute(select(runs.c.trace).where(runs.c.id == run_id))).first()


async def progress_of(conn: AsyncConnection, run_id: uuid.UUID) -> Any:
    """Status, usage and trace of a run that is known to exist."""
    return (
        await conn.execute(
            select(runs.c.status, runs.c.usage, runs.c.trace).where(runs.c.id == run_id)
        )
    ).one()


# --------------------------------------------------------------------------- BOM versions
async def latest_version(conn: AsyncConnection, run_id: uuid.UUID) -> Any | None:
    return (
        await conn.execute(
            select(bom_versions.c.id, bom_versions.c.version, bom_versions.c.content)
            .where(bom_versions.c.run_id == run_id)
            .order_by(bom_versions.c.version.desc())
            .limit(1)
        )
    ).first()


async def version_content(conn: AsyncConnection, run_id: uuid.UUID, version: int) -> Any | None:
    """Content of one version. ``text`` on purpose: the client-supplied number is bound
    untyped, so a value beyond the column's integer range matches nothing (404) instead of
    failing the cast with a 500."""
    row = (
        await conn.execute(
            text("SELECT content FROM bom.versions WHERE run_id = :r AND version = :v"),
            {"r": run_id, "v": version},
        )
    ).first()
    return row.content if row is not None else None


async def version_history(conn: AsyncConnection, run_id: uuid.UUID) -> list[dict[str, Any]]:
    """Newest first, with the parent version number and line/finding counts (jsonb functions
    have no Core counterpart worth the indirection, hence ``text``)."""
    rows = await conn.execute(
        text(
            "SELECT v.version, p.version AS parent_version, v.reason, v.created_by,"
            " v.created_at, jsonb_array_length(v.content->'items') AS lines,"
            " jsonb_array_length(COALESCE(v.content->'findings', '[]'::jsonb)) AS findings"
            " FROM bom.versions v LEFT JOIN bom.versions p ON p.id = v.parent_id"
            " WHERE v.run_id = :r ORDER BY v.version DESC"
        ),
        {"r": run_id},
    )
    return [dict(r._mapping) for r in rows]


async def insert_version(
    conn: AsyncConnection,
    *,
    run_id: uuid.UUID,
    version: int,
    parent_id: uuid.UUID,
    content_json: str,
    reason: str,
    created_by: str,
) -> None:
    await conn.execute(
        insert(bom_versions).values(
            id=uuid.uuid4(),
            tenant_id=func.app.current_tenant_id(),
            run_id=run_id,
            version=version,
            parent_id=parent_id,
            content=cast(literal(content_json, Text), JSONB),
            reason=reason,
            created_by=created_by,
        )
    )
