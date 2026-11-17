"""SQL of organisation onboarding (``tenancy.tenants`` + first ``tenancy.memberships`` row)."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def create_with_owner(
    conn: AsyncConnection,
    *,
    org_id: uuid.UUID,
    slug: str,
    name: str,
    owner_sub: str,
    owner_email: str,
    owner_name: str,
) -> None:
    """Create the tenant and its first owner, then scope the connection to the new tenant.

    One SECURITY DEFINER function does both inserts (SEC-15): the platform role itself can no
    longer insert tenants or memberships."""
    await conn.execute(
        text("SELECT tenancy.create_organization(:i, :s, :n, :sub, :e, :d)"),
        {
            "i": org_id,
            "s": slug,
            "n": name,
            "sub": owner_sub,
            "e": owner_email.lower(),
            "d": owner_name,
        },
    )
    await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org_id)})
