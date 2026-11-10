"""Plan limits (ARCHITECTURE §5 onboarding: "limity planu"; SECURITY.md: request limits
per tenant and API key). Kept as reviewed code; the plan of a tenant is
``tenancy.tenants.plan`` and only the platform role can change it.

Limits are enforced in the API (requests, projects, runs, monthly LLM budget) and per
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


@dataclass(frozen=True)
class Plan:
    requests_per_minute: int  # per user or API key
    max_projects: int
    max_concurrent_runs: int  # queued + running
    max_runs_per_month: int
    llm_budget_eur_per_month: float


PLANS: dict[str, Plan] = {
    "pilot": Plan(120, 20, 2, 200, 50.0),
    "team": Plan(600, 200, 5, 2_000, 500.0),
    "business": Plan(1_200, 1_000, 10, 10_000, 2_500.0),
    "enterprise": Plan(3_000, 10_000, 25, 100_000, 25_000.0),
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
    count = (await conn.execute(text("SELECT count(*) FROM projects.projects"))).scalar() or 0
    if count >= plan.max_projects:
        raise quota_exceeded(f"plan allows {plan.max_projects} projects")


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


async def usage_report(conn: AsyncConnection) -> dict[str, Any]:
    plan = await plan_of(conn)
    return {"usage": await month_to_date(conn), "limits": plan.__dict__}
