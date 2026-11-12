from __future__ import annotations

import uuid

import pytest

from bomagent_common.tenancy import (
    MissingTenantContextError,
    TenantContext,
    current_tenant,
    require_tenant,
    tenant_scope,
)


def test_require_tenant_without_context_raises():
    with pytest.raises(MissingTenantContextError):
        require_tenant()


def test_scope_sets_and_restores_context():
    ctx = TenantContext(tenant_id=uuid.uuid4(), actor_id="u1", roles=frozenset({"engineer"}))
    with tenant_scope(ctx):
        assert require_tenant() is ctx
        assert ctx.has_role("engineer", "admin")
        assert not ctx.has_role("owner")
    assert current_tenant() is None


def test_nested_scopes_restore_outer():
    outer = TenantContext(tenant_id=uuid.uuid4(), actor_id="a")
    inner = TenantContext(tenant_id=uuid.uuid4(), actor_id="b")
    with tenant_scope(outer), tenant_scope(inner):
        assert require_tenant() is inner
    assert current_tenant() is None
