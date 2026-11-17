"""Downgrade/upgrade round trip of the audit revisions (0015 onboarding function, 0016 indexes).

A scratch database is migrated to head, taken back to 0014 (the previous head) and forward
again. Older revisions are not downgraded (the SSO revision's downgrade is a known defect).
"""

from __future__ import annotations

import secrets

import pytest
from sqlalchemy import create_engine, make_url, text

from bomagent_migrations import downgrade, prepare_database, upgrade
from bomagent_testing.fixtures import DbUrls

pytestmark = pytest.mark.integration

FN = "tenancy.create_organization(uuid,text,text,text,text,text)"


def _url(base: str, **parts: str) -> str:
    return make_url(base).set(**parts).render_as_string(hide_password=False)


def _scalar(url: str, sql: str) -> object:
    eng = create_engine(url)
    with eng.connect() as conn:
        value = conn.execute(text(sql)).scalar_one()
    eng.dispose()
    return value


def _state(url: str) -> dict[str, object]:
    return {
        "function": _scalar(url, f"SELECT to_regprocedure('{FN}') IS NOT NULL"),
        "runs_index": _scalar(url, "SELECT to_regclass('runs.runs_project_status') IS NOT NULL"),
        "files_index": _scalar(url, "SELECT to_regclass('projects.files_project') IS NOT NULL"),
        "platform_insert_tenants": _scalar(
            url, "SELECT has_table_privilege('bomagent_platform', 'tenancy.tenants', 'INSERT')"
        ),
        "platform_memberships": _scalar(
            url, "SELECT has_table_privilege('bomagent_platform', 'tenancy.memberships', 'SELECT')"
        ),
        "policies": _scalar(
            url,
            "SELECT string_agg(tablename || '.' || policyname, ',' ORDER BY tablename, policyname)"
            " FROM pg_policies WHERE schemaname = 'tenancy' AND tablename IN"
            " ('tenants', 'memberships')",
        ),
        "invalid_indexes": _scalar(url, "SELECT count(*) FROM pg_index WHERE NOT indisvalid"),
    }


def test_new_revisions_downgrade_and_upgrade_again(db_urls: DbUrls) -> None:
    root = _url(db_urls.admin, database="postgres")
    db = f"test_roundtrip_{secrets.token_hex(4)}"
    eng = create_engine(root, isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {db}"))
    eng.dispose()
    admin, migrator = _url(db_urls.admin, database=db), _url(db_urls.migrator, database=db)
    try:
        prepare_database(admin)
        upgrade(migrator)
        head = _state(admin)
        assert head["function"]
        assert head["runs_index"]
        assert head["files_index"]
        assert not head["platform_insert_tenants"]
        assert not head["platform_memberships"]
        assert "platform_onboarding" not in str(head["policies"])
        for name in (
            "memberships.migrator_create_organization",
            "tenants.migrator_create_organization",
            "tenants.platform_tenants_read",
            "tenants.platform_tenants_update",
        ):
            assert name in str(head["policies"])

        downgrade(migrator, "0015")  # indexes only
        step = _state(admin)
        assert step["function"]
        assert not step["runs_index"]
        assert not step["files_index"]

        downgrade(migrator, "0014")  # onboarding function and grants
        old = _state(admin)
        assert not old["function"]
        assert old["platform_insert_tenants"]
        assert old["platform_memberships"]
        assert "platform_onboarding" in str(old["policies"])
        assert "migrator_create_organization" not in str(old["policies"])

        upgrade(migrator)  # and forward again
        assert _state(admin) == head
        assert head["invalid_indexes"] == 0
    finally:
        eng = create_engine(root, isolation_level="AUTOCOMMIT")
        with eng.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)"))
        eng.dispose()
