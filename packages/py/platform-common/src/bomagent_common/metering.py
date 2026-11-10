"""Usage metering per tenant and day (``metering.usage_daily``, RLS).

Called inside the tenant transaction that performs the metered work, so a rolled-back
operation is never counted.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

COUNTERS = (
    "runs",
    "llm_calls",
    "input_tokens",
    "output_tokens",
    "cost_eur",
    "files_uploaded",
    "bytes_uploaded",
)


async def record_usage(conn: AsyncConnection, **counters: float) -> None:
    """Add ``counters`` (names from :data:`COUNTERS`) to today's row of the active tenant."""
    unknown = set(counters) - set(COUNTERS)
    if unknown:
        raise ValueError(f"unknown usage counters: {sorted(unknown)}")
    if not counters:
        return
    cols = ", ".join(counters)
    params = ", ".join(f":{c}" for c in counters)
    sets = ", ".join(f"{c} = usage_daily.{c} + EXCLUDED.{c}" for c in counters)
    await conn.execute(
        text(
            f"INSERT INTO metering.usage_daily (tenant_id, day, {cols})"  # noqa: S608 - fixed names
            f" VALUES (app.current_tenant_id(), current_date, {params})"
            f" ON CONFLICT (tenant_id, day) DO UPDATE SET {sets}"
        ),
        counters,
    )


async def month_to_date(conn: AsyncConnection) -> dict[str, float]:
    """Totals of the active tenant for the current calendar month."""
    sums = ", ".join(f"COALESCE(sum({c}), 0) AS {c}" for c in COUNTERS)
    row = (
        await conn.execute(
            text(
                f"SELECT {sums} FROM metering.usage_daily"  # noqa: S608 - fixed names
                " WHERE tenant_id = app.current_tenant_id()"
                " AND day >= date_trunc('month', current_date)::date"
            )
        )
    ).one()
    return {c: float(getattr(row, c)) for c in COUNTERS}
