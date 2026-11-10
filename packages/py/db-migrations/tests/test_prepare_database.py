"""Database preparation as the AWS bootstrap task runs it: a non-superuser administrator."""

from __future__ import annotations

import secrets

import pytest
from sqlalchemy import create_engine, make_url, text

from bomagent_migrations import (
    APP_ROLE,
    MIGRATOR_ROLE,
    PLATFORM_ROLE,
    admin_url_from_env,
    passwords_from_env,
    prepare_database,
    upgrade,
)
from bomagent_testing.fixtures import DbUrls

pytestmark = pytest.mark.integration


def _exec(url: str, *sql: str) -> None:
    eng = create_engine(url, isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        for stmt in sql:
            conn.execute(text(stmt))
    eng.dispose()


def test_aurora_like_admin_prepares_a_database_the_migrator_can_migrate(db_urls: DbUrls) -> None:
    root = make_url(db_urls.admin).set(drivername="postgresql+psycopg")
    tag = secrets.token_hex(4)
    admin, admin_pw, db = f"test_admin_{tag}", secrets.token_hex(12), f"test_prep_{tag}"
    # like the Aurora master user: CREATEDB + CREATEROLE, no superuser, owns the database
    _exec(
        root.render_as_string(hide_password=False),
        f"CREATE ROLE {admin} LOGIN CREATEDB CREATEROLE PASSWORD '{admin_pw}'",
        f"CREATE DATABASE {db} OWNER {admin}",
        # what PostgreSQL 16 gives the creator of a role (the master creates ours in Aurora)
        f"GRANT {MIGRATOR_ROLE}, {APP_ROLE}, {PLATFORM_ROLE} TO {admin}"
        " WITH ADMIN TRUE, INHERIT FALSE, SET FALSE",
    )
    admin_url = root.set(username=admin, password=admin_pw, database=db)
    # Aurora lets rds_superuser install pgvector; a plain local non-superuser cannot, so
    # the extension is pre-installed here (prepare_database's CREATE ... IF NOT EXISTS
    # is then a no-op). Everything else below runs as the non-superuser administrator.
    _exec(
        root.set(database=db).render_as_string(hide_password=False),
        "CREATE EXTENSION IF NOT EXISTS vector",
    )
    migrator_url = make_url(db_urls.migrator).set(database=db)
    try:
        prepare_database(admin_url.render_as_string(hide_password=False))
        prepare_database(admin_url.render_as_string(hide_password=False))  # idempotent
        eng = create_engine(admin_url.render_as_string(hide_password=False))
        with eng.connect() as conn:
            owner = conn.execute(
                text(
                    "SELECT pg_get_userbyid(datdba) FROM pg_database"
                    " WHERE datname = current_database()"
                )
            ).scalar_one()
            vector = conn.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one()
            connect = conn.execute(
                text("SELECT has_database_privilege(:r, current_database(), 'CONNECT')"),
                {"r": APP_ROLE},
            ).scalar_one()
        eng.dispose()
        assert owner == MIGRATOR_ROLE
        assert vector == 1
        assert connect is True
        upgrade(migrator_url.render_as_string(hide_password=False))
    finally:
        _exec(
            root.render_as_string(hide_password=False),
            f"DROP DATABASE IF EXISTS {db} WITH (FORCE)",
            f"DROP ROLE IF EXISTS {admin}",
        )


def test_admin_url_is_composed_with_special_characters_escaped() -> None:
    url = admin_url_from_env(
        {
            "BOMAGENT_ADMIN_USER": "bomagent_admin",
            "BOMAGENT_ADMIN_PASSWORD": "p@ss:w/rd%#?",
            "BOMAGENT_DATABASE_HOST": "db.internal",
        }
    )
    parsed = make_url(url)
    assert parsed.password == "p@ss:w/rd%#?"
    assert parsed.host == "db.internal"
    assert parsed.database == "bomagent"
    assert parsed.query["sslmode"] == "require"
    assert admin_url_from_env({"BOMAGENT_ADMIN_DATABASE_URL": "postgresql://x"}) == (
        "postgresql://x"
    )


def test_only_present_passwords_are_set() -> None:
    env = {"BOMAGENT_APP_PASSWORD": "a", "BOMAGENT_PLATFORM_PASSWORD": ""}
    assert passwords_from_env(env) == {APP_ROLE: "a"}
    assert PLATFORM_ROLE not in passwords_from_env(env)
