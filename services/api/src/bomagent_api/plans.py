"""Plan limits (ARCHITECTURE §5 onboarding: "limity planu"; SECURITY.md: request limits
per tenant and API key). Kept as reviewed code; the plan of a tenant is
``tenancy.tenants.plan`` and only the platform role can change it.

Limits are enforced in the API (requests, projects, runs, monthly LLM budget, storage) and per
run by the agent budgets; the LLM gateway keeps its own per-tenant budget as a backstop.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bomagent_common.metering import month_to_date
from bomagent_common.problems import ProblemError

GIB = 1024**3


@dataclass(frozen=True)
class Plan:
    requests_per_minute: int  # per user or API key
    max_projects: int
    max_concurrent_runs: int  # queued + running
    max_runs_per_month: int
    llm_budget_eur_per_month: float
    storage_bytes: int  # total size of uploaded design files per organisation


PLANS: dict[str, Plan] = {
    "pilot": Plan(120, 20, 2, 200, 50.0, 2 * GIB),
    "team": Plan(600, 200, 5, 2_000, 500.0, 20 * GIB),
    "business": Plan(1_200, 1_000, 10, 10_000, 2_500.0, 100 * GIB),
    "enterprise": Plan(3_000, 10_000, 25, 100_000, 25_000.0, 1_000 * GIB),
}
MAX_OWNED_ORGANIZATIONS = 3  # per user: blocks slug squatting by self-service sign-ups


def quota_exceeded(detail: str) -> ProblemError:
    return ProblemError(429, "Too Many Requests", detail, slug="quota-exceeded")


async def plan_of(conn: AsyncConnection, *, lock: bool = False) -> Plan:
    """``lock`` serialises quota checks of one tenant until the transaction ends."""
    name = (
        await conn.execute(
            text(
                "SELECT plan FROM tenancy.tenants WHERE id = app.current_tenant_id()"  # noqa: S608
                + (" FOR NO KEY UPDATE" if lock else "")
            )
        )
    ).scalar()
    return PLANS[str(name)]


async def hit_rate_limit(conn: AsyncConnection, subject: str, plan: Plan) -> None:
    """Fixed one-minute window per subject, shared by all replicas (Postgres UPSERT)."""
    hits = (
        await conn.execute(
            text(
                "INSERT INTO app.rate_windows (tenant_id, subject, window_start, hits)"
                " VALUES (app.current_tenant_id(), :s, date_trunc('minute', now()), 1)"
                " ON CONFLICT (tenant_id, subject, window_start)"
                " DO UPDATE SET hits = rate_windows.hits + 1 RETURNING hits,"
                " extract(epoch FROM date_trunc('minute', now()) + interval '1 minute'"
                " - now()) AS reset_s"
            ),
            {"s": subject},
        )
    ).one()
    if hits.hits == 1:  # first hit of a window: drop this subject's old windows
        await conn.execute(
            text(
                "DELETE FROM app.rate_windows WHERE tenant_id = app.current_tenant_id()"
                " AND subject = :s AND window_start < date_trunc('minute', now())"
            ),
            {"s": subject},
        )
    if hits.hits > plan.requests_per_minute:
        raise ProblemError(
            429,
            "Too Many Requests",
            f"limit of {plan.requests_per_minute} requests per minute reached",
            slug="rate-limited",
            headers={"Retry-After": str(max(1, math.ceil(float(hits.reset_s))))},
        )


async def check_new_project(conn: AsyncConnection) -> None:
    plan = await plan_of(conn, lock=True)
    # sample projects added by the platform are exempt from the quota
    count = (
        await conn.execute(text("SELECT count(*) FROM projects.projects WHERE sample_key IS NULL"))
    ).scalar() or 0
    if count >= plan.max_projects:
        raise quota_exceeded(f"plan allows {plan.max_projects} projects")


async def check_storage(conn: AsyncConnection, new_bytes: int, replaced_bytes: int = 0) -> None:
    """Total size of the organisation's design files after an upload (a replaced file
    counts once). The caller holds the tenant lock (``plan_of(lock=True)``)."""
    plan = await plan_of(conn, lock=True)
    used = (
        await conn.execute(text("SELECT COALESCE(sum(size_bytes), 0) FROM projects.files"))
    ).scalar() or 0
    if int(used) - replaced_bytes + new_bytes > plan.storage_bytes:
        raise quota_exceeded(f"plan allows {plan.storage_bytes} bytes of design files in storage")


async def check_new_run(conn: AsyncConnection) -> None:
    plan = await plan_of(conn, lock=True)
    active = (
        await conn.execute(
            text("SELECT count(*) FROM runs.runs WHERE status IN ('queued', 'running')")
        )
    ).scalar() or 0
    if active >= plan.max_concurrent_runs:
        raise quota_exceeded(f"plan allows {plan.max_concurrent_runs} concurrent runs")
    month = (
        await conn.execute(
            text("SELECT count(*) FROM runs.runs WHERE created_at >= date_trunc('month', now())")
        )
    ).scalar() or 0
    if month >= plan.max_runs_per_month:
        raise quota_exceeded(f"plan allows {plan.max_runs_per_month} runs per month")
    usage = await month_to_date(conn)
    if usage["cost_eur"] >= plan.llm_budget_eur_per_month:
        raise quota_exceeded("monthly LLM budget of the plan is used up")


async def plan_name(conn: AsyncConnection) -> str:
    return str(
        (
            await conn.execute(
                text("SELECT plan FROM tenancy.tenants WHERE id = app.current_tenant_id()")
            )
        ).scalar()
    )


async def usage_report(conn: AsyncConnection) -> dict[str, Any]:
    plan = await plan_of(conn)
    return {
        "plan": await plan_name(conn),
        "usage": await month_to_date(conn),
        "limits": plan.__dict__,
    }
