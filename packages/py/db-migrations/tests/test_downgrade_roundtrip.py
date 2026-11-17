"""Every revision can be rolled back and re-applied, and the schema comes back identical (OPS-08).

Runs in CI (needs PostgreSQL + pgvector through ``db_urls``). It uses a database of its own so
the shared session database that other integration tests use stays at ``head``.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text

from bomagent_migrations import (
    APP_ROLE,
    MIGRATOR_ROLE,
    PLATFORM_ROLE,
    downgrade,
    prepare_database,
    upgrade,
)
from bomagent_testing.fixtures import DbUrls

pytestmark = pytest.mark.integration

VERSIONS = Path(__file__).resolve().parents[1] / "src/bomagent_migrations/versions"

_FINGERPRINT = [
    """SELECT 'column', table_schema || '.' || table_name || '.' || column_name || ' '
              || data_type || ' ' || is_nullable || ' ' || coalesce(column_default, '')
       FROM information_schema.columns
       WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'public')""",
    """SELECT 'index', schemaname || '.' || indexname || ' ' || indexdef FROM pg_indexes
       WHERE schemaname NOT IN ('pg_catalog', 'information_schema', 'public')""",
    """SELECT 'policy', schemaname || '.' || tablename || '.' || policyname || ' ' || cmd
              || ' ' || coalesce(qual, '') || ' ' || coalesce(with_check, '')
       FROM pg_policies""",
    """SELECT 'rls', n.nspname || '.' || c.relname || ' ' || c.relrowsecurity || ' '
              || c.relforcerowsecurity
       FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE c.relkind = 'r' AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'public')""",
    """SELECT 'constraint', conrelid::regclass::text || ' ' || conname || ' '
              || pg_get_constraintdef(oid)
       FROM pg_constraint
       WHERE connamespace NOT IN ('pg_catalog'::regnamespace, 'information_schema'::regnamespace,
                                  'public'::regnamespace)""",
]


def _fingerprint(url: str) -> list[tuple[str, str]]:
    eng = create_engine(url)
    try:
        with eng.connect() as conn:
            rows = [tuple(r) for q in _FINGERPRINT for r in conn.execute(text(q)).all()]
    finally:
        eng.dispose()
    return sorted((str(a), str(b)) for a, b in rows)


@pytest.fixture
def fresh_db(db_urls: DbUrls) -> Iterator[str]:
    """A prepared (roles, extensions) but unmigrated database; yields the migrator URL."""
    base = make_url(db_urls.admin).set(drivername="postgresql+psycopg")
    name = f"bomagent_roundtrip_{secrets.token_hex(4)}"
    # roles are cluster-wide: reuse the session database's passwords, or this fixture would
    # change them under the other tests that share the cluster
    pwds = {
        MIGRATOR_ROLE: make_url(db_urls.migrator).password or secrets.token_hex(16),
        APP_ROLE: make_url(db_urls.app).password or secrets.token_hex(16),
        PLATFORM_ROLE: make_url(db_urls.platform).password or secrets.token_hex(16),
    }
    root = create_engine(base.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    with root.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        db_admin = base.set(database=name)
        prepare_database(db_admin.render_as_string(hide_password=False), pwds)
        yield db_admin.set(username=MIGRATOR_ROLE, password=pwds[MIGRATOR_ROLE]).render_as_string(
            hide_password=False
        )
    finally:
        with root.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        root.dispose()


def test_one_step_down_and_up_restores_the_schema(fresh_db: str) -> None:
    upgrade(fresh_db)
    before = _fingerprint(fresh_db)
    assert before, "the fingerprint query found no schema objects"
    downgrade(fresh_db, "-1")
    assert _fingerprint(fresh_db) != before, "downgrade -1 changed nothing"
    upgrade(fresh_db)
    assert _fingerprint(fresh_db) == before


def test_every_revision_downgrades_in_turn_and_head_is_rebuilt(fresh_db: str) -> None:
    revisions = [p for p in VERSIONS.glob("*.py") if not p.name.startswith("__")]
    assert len(revisions) >= 14
    upgrade(fresh_db)
    at_head = _fingerprint(fresh_db)
    for _ in revisions:  # one step at a time: each downgrade() must work on its own
        downgrade(fresh_db, "-1")
    downgrade(fresh_db, "base")  # already at base: a no-op, proves nothing is left to undo
    upgrade(fresh_db)
    assert _fingerprint(fresh_db) == at_head
