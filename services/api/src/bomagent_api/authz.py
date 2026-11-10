"""Authorisation policies as data (Cedar-style: principal role -> action), ADR-0005.

Kept as a small table so it can be reviewed in one place and later exported to Amazon
Verified Permissions / Cedar without changing call sites.
"""

from __future__ import annotations

from bomagent_common.problems import ProblemError
from bomagent_common.tenancy import TenantContext

READ = frozenset({"owner", "admin", "engineer", "reviewer", "viewer"})
WRITE = frozenset({"owner", "admin", "engineer"})
REVIEW = frozenset({"owner", "admin", "engineer", "reviewer"})
ADMIN = frozenset({"owner", "admin"})

POLICIES: dict[str, frozenset[str]] = {
    "project.read": READ,
    "project.create": WRITE,
    "file.upload": WRITE,
    "run.read": READ,
    "run.create": WRITE,
    "bom.read": READ,
    "bom.edit": REVIEW,
    "bom.export": READ,
    "audit.read": ADMIN | {"reviewer"},
    "member.read": ADMIN,
    "member.invite": ADMIN,
    "member.manage": ADMIN,
    "apikey.manage": ADMIN,
    "org.update": ADMIN,
}


def allowed(ctx: TenantContext, action: str) -> bool:
    return bool(ctx.roles & POLICIES[action])


def require(ctx: TenantContext, action: str) -> None:
    if not allowed(ctx, action):
        raise ProblemError(
            403, "Forbidden", f"role does not allow {action}", slug="forbidden-action"
        )
