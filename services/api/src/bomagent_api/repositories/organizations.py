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
    """Create the tenant and its first owner, then scope the connection to the new tenant
    (platform role: the application role cannot create tenants)."""
    await conn.execute(
        text("INSERT INTO tenancy.tenants (id, slug, name) VALUES (:i, :s, :n)"),
        {"i": org_id, "s": slug, "n": name},
    )
    await conn.execute(
        text(
            "INSERT INTO tenancy.memberships (tenant_id, user_sub, email,"
            " display_name, roles) VALUES (:t, :s, :e, :d,"
            " ARRAY['owner'])"
        ),
        {"t": org_id, "s": owner_sub, "e": owner_email.lower(), "d": owner_name},
    )
    await conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(org_id)})
