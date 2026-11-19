"""SQL of projects and their design files (``projects.projects``, ``projects.files``)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_api.repositories.tables import bom_versions, files, projects, runs

_PROJECT_COLS = (
    projects.c.id,
    projects.c.name,
    projects.c.description,
    projects.c.created_by,
    projects.c.created_at,
    projects.c.sample_key.is_not(None).label("is_sample"),
)
_FILE_COLS = (
    files.c.id,
    files.c.name,
    files.c.size_bytes,
    files.c.sha256,
    files.c.status,
    files.c.detected_format,
    files.c.summary,
    files.c.created_at,
)


async def get(conn: AsyncConnection, project_id: uuid.UUID) -> dict[str, Any] | None:
    row = (await conn.execute(select(*_PROJECT_COLS).where(projects.c.id == project_id))).first()
    return dict(row._mapping) if row is not None else None


async def list_page(
    conn: AsyncConnection, *, after: ColumnElement[bool] | None, limit: int
) -> list[dict[str, Any]]:
    """Newest first; ``after`` is the keyset predicate from ``pagination.page_filter``."""
    stmt = select(*_PROJECT_COLS)
    if after is not None:
        stmt = stmt.where(after)
    stmt = stmt.order_by(projects.c.created_at.desc(), projects.c.id.desc()).limit(limit)
    return [dict(r._mapping) for r in await conn.execute(stmt)]


async def insert_project(
    conn: AsyncConnection, *, project_id: uuid.UUID, name: str, description: str, created_by: str
) -> None:
    await conn.execute(
        insert(projects).values(
            id=project_id,
            tenant_id=func.app.current_tenant_id(),
            name=name,
            description=description,
            created_by=created_by,
        )
    )


async def lock(conn: AsyncConnection, project_id: uuid.UUID) -> Any | None:
    """Row lock (``FOR UPDATE``): name, description and sample key, or None."""
    return (
        await conn.execute(
            select(projects.c.name, projects.c.description, projects.c.sample_key)
            .where(projects.c.id == project_id)
            .with_for_update()
        )
    ).first()


async def update_project(
    conn: AsyncConnection, project_id: uuid.UUID, *, name: str | None, description: str | None
) -> None:
    """Only the fields that are not None change."""
    await conn.execute(
        update(projects)
        .where(projects.c.id == project_id)
        .values(
            name=func.coalesce(name, projects.c.name),
            description=func.coalesce(description, projects.c.description),
        )
    )


async def delete_project(conn: AsyncConnection, project_id: uuid.UUID) -> None:
    await conn.execute(delete(projects).where(projects.c.id == project_id))


async def object_keys(conn: AsyncConnection, project_id: uuid.UUID) -> list[str]:
    return list(
        (
            await conn.execute(select(files.c.object_key).where(files.c.project_id == project_id))
        ).scalars()
    )


async def parsed_object_keys(conn: AsyncConnection, project_id: uuid.UUID) -> list[str]:
    """Object keys of the files the ingest worker has accepted, in name order."""
    return list(
        (
            await conn.execute(
                select(files.c.object_key)
                .where(files.c.project_id == project_id, files.c.status == "parsed")
                .order_by(files.c.name)
            )
        ).scalars()
    )


async def run_ids(conn: AsyncConnection, project_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (await conn.execute(select(runs.c.id).where(runs.c.project_id == project_id))).scalars()
    )


async def bom_version_count(conn: AsyncConnection, project_id: uuid.UUID) -> int:
    count = (
        await conn.execute(
            select(func.count())
            .select_from(bom_versions)
            .where(
                bom_versions.c.run_id.in_(select(runs.c.id).where(runs.c.project_id == project_id))
            )
        )
    ).scalar()
    return int(count or 0)


async def delete_queued_outbox_of_project(conn: AsyncConnection, project_id: uuid.UUID) -> None:
    """Queued (unsent) ingest work of the project goes with it."""
    await conn.execute(
        text(
            "DELETE FROM app.outbox WHERE sent_at IS NULL"
            " AND message->'payload'->>'project_id' = :p"
        ),
        {"p": str(project_id)},
    )


async def delete_queued_outbox_of_file(conn: AsyncConnection, file_id: uuid.UUID) -> None:
    """A queued ingest of a deleted file has nothing left to parse."""
    await conn.execute(
        text(
            "DELETE FROM app.outbox WHERE sent_at IS NULL AND message->'payload'->>'file_id' = :f"
        ),
        {"f": str(file_id)},
    )


# ----------------------------------------------------------------------------- files
async def list_files(conn: AsyncConnection, project_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await conn.execute(
        select(*_FILE_COLS).where(files.c.project_id == project_id).order_by(files.c.name)
    )
    return [dict(r._mapping) for r in rows]


async def get_file_by_name(
    conn: AsyncConnection, project_id: uuid.UUID, name: str
) -> dict[str, Any]:
    row = (
        await conn.execute(
            select(*_FILE_COLS).where(files.c.project_id == project_id, files.c.name == name)
        )
    ).one()
    return dict(row._mapping)


async def lock_file(conn: AsyncConnection, project_id: uuid.UUID, file_id: uuid.UUID) -> Any | None:
    return (
        await conn.execute(
            select(files.c.name, files.c.object_key, files.c.sha256, files.c.size_bytes)
            .where(files.c.id == file_id, files.c.project_id == project_id)
            .with_for_update()
        )
    ).first()


async def lock_file_by_name(conn: AsyncConnection, project_id: uuid.UUID, name: str) -> Any | None:
    return (
        await conn.execute(
            select(files.c.object_key, files.c.sha256, files.c.size_bytes)
            .where(files.c.project_id == project_id, files.c.name == name)
            .with_for_update()
        )
    ).first()


async def delete_file(conn: AsyncConnection, file_id: uuid.UUID) -> None:
    await conn.execute(delete(files).where(files.c.id == file_id))


async def file_totals(conn: AsyncConnection, project_id: uuid.UUID) -> tuple[int, int]:
    """Number of files and total bytes of a project."""
    count, total = (
        await conn.execute(
            select(func.count(), func.coalesce(func.sum(files.c.size_bytes), 0)).where(
                files.c.project_id == project_id
            )
        )
    ).one()
    return int(count), int(total)


async def upsert_file(
    conn: AsyncConnection,
    *,
    file_id: uuid.UUID,
    project_id: uuid.UUID,
    name: str,
    object_key: str,
    sha256: str,
    size_bytes: int,
    created_by: str,
) -> None:
    """Insert, or replace the file of the same name (back to ``uploaded`` with no summary)."""
    stmt = pg_insert(files).values(
        id=file_id,
        tenant_id=func.app.current_tenant_id(),
        project_id=project_id,
        name=name,
        object_key=object_key,
        sha256=sha256,
        size_bytes=size_bytes,
        created_by=created_by,
    )
    excluded = stmt.excluded
    await conn.execute(
        stmt.on_conflict_do_update(
            index_elements=[files.c.tenant_id, files.c.project_id, files.c.name],
            set_={
                "object_key": excluded.object_key,
                "sha256": excluded.sha256,
                "size_bytes": excluded.size_bytes,
                "status": "uploaded",
                "summary": {},
                # the upload time of the current bytes: the maintenance sweep measures how
                # long a file waits for its ingest from here
                "created_at": func.now(),
            },
        )
    )
