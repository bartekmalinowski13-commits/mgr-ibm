"""Async database access with Row-Level Security enforcement.

Every transaction touching tenant data must go through :func:`tenant_transaction`, which
sets ``app.tenant_id`` with ``set_config(..., is_local => true)`` - the equivalent of
``SET LOCAL`` that also accepts bind parameters (no SQL injection through the tenant id).
The application connects as ``bomagent_app`` which has no ``BYPASSRLS``; policies in the
migrations compare rows against ``app.current_tenant_id()``.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    create_async_engine,
)

from bomagent_common.tenancy import require_tenant


def make_engine(url: str, *, pool_size: int = 5, echo: bool = False) -> AsyncEngine:
    """Create an engine. ``url`` uses the psycopg 3 driver (``postgresql+psycopg://``)."""
    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=pool_size,
        pool_pre_ping=True,
        echo=echo,
        hide_parameters=True,  # bound values (customer data) never reach logs/exceptions
    )


@contextlib.asynccontextmanager
async def tenant_transaction(
    engine: AsyncEngine, tenant_id: uuid.UUID | None = None
) -> AsyncIterator[AsyncConnection]:
    """Open a transaction bound to one tenant.

    ``tenant_id`` defaults to the active :class:`TenantContext`. The setting is
    transaction-local, so a pooled connection never leaks the tenant to the next user.
    """
    tid = tenant_id if tenant_id is not None else require_tenant().tenant_id
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tid)}
        )
        yield conn


@contextlib.asynccontextmanager
async def platform_transaction(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Transaction without tenant context (platform role, e.g. global KB pipeline).

    RLS still applies: with no ``app.tenant_id`` only rows that policies grant to the
    connected role (e.g. ``scope = 'global'``) are visible.
    """
    async with engine.begin() as conn:
        yield conn


async def ping(engine: AsyncEngine) -> bool:
    """Readiness probe helper."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
