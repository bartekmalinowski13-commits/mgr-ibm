"""Helpers for API tests."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_common.db import tenant_transaction


async def mark_files_parsed(engine: AsyncEngine, org_id: str | uuid.UUID) -> None:
    """Stand-in for the sandboxed ingest worker when a test does not parse real files."""
    async with tenant_transaction(engine, uuid.UUID(str(org_id))) as conn:
        await conn.execute(text("UPDATE projects.files SET status = 'parsed'"))
