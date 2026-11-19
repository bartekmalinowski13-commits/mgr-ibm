"""Authorisation policies as data (Cedar-style: principal role -> action), ADR-0005.

Kept as a small table so it can be reviewed in one place and later exported to Amazon
Verified Permissions / Cedar without changing call sites.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from bomagent_common.audit import AuditEvent, emit_audit
from bomagent_common.db import tenant_transaction
from bomagent_common.logging import get_logger
from bomagent_common.problems import ProblemError, problem_response
from bomagent_common.tenancy import TenantContext

log = get_logger(__name__)

READ = frozenset({"owner", "admin", "engineer", "reviewer", "viewer"})
WRITE = frozenset({"owner", "admin", "engineer"})
REVIEW = frozenset({"owner", "admin", "engineer", "reviewer"})
ADMIN = frozenset({"owner", "admin"})

POLICIES: dict[str, frozenset[str]] = {
    "project.read": READ,
    "project.create": WRITE,
    "project.delete": ADMIN,  # any project, sample or own (UX-03)
    "samples.add": frozenset({"owner"}),
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
    "usage.read": ADMIN,
    "kb.read": READ,
    "kb.write": WRITE,
    "org.update": ADMIN,
    "sso.manage": ADMIN,
}


#: Actions that need a second factor when ``Settings.mfa_enforced`` is on (SEC-06: member,
#: API key, SSO and organisation management). Reading, exports and project work do not.
MFA_ACTIONS = frozenset(
    {"member.manage", "member.invite", "apikey.manage", "sso.manage", "org.update"}
)


class MfaRequiredError(ProblemError):
    """403 ``mfa-required``: the role allows the action but the token has no MFA proof."""

    def __init__(self, ctx: TenantContext, action: str) -> None:
        super().__init__(
            403,
            "Forbidden",
            "this action needs multi-factor authentication",
            slug="mfa-required",
            headers={"WWW-Authenticate": 'Bearer error="insufficient_user_authentication"'},
        )
        self.ctx, self.action = ctx, action


async def mfa_required_handler(request: Request, exc: Exception) -> JSONResponse:
    """Problem response plus an audit event (best effort: a failing audit write must not
    turn the 403 into a 500)."""
    assert isinstance(exc, MfaRequiredError)
    try:
        async with tenant_transaction(request.app.state.engine, exc.ctx.tenant_id) as conn:
            await emit_audit(
                conn,
                AuditEvent(
                    action="auth.mfa_required",
                    object_type="action",
                    object_id=exc.action,
                ),
                exc.ctx,
            )
    except Exception:
        log.exception("mfa_denial_audit_failed", action=exc.action)
    response = problem_response(exc.problem.model_copy(), request)
    response.headers.update(exc.headers)
    return response


def allowed(ctx: TenantContext, action: str) -> bool:
    return bool(ctx.roles & POLICIES[action])


def require(ctx: TenantContext, action: str) -> None:
    if not allowed(ctx, action):
        raise ProblemError(
            403, "Forbidden", f"role does not allow {action}", slug="forbidden-action"
        )
    # step-up (SEC-06): only when enforcement is on (``ctx.mfa`` is not None) and the token
    # shows no second factor; the role check comes first so a non-admin learns nothing
    if ctx.mfa is False and action in MFA_ACTIONS:
        raise MfaRequiredError(ctx, action)
