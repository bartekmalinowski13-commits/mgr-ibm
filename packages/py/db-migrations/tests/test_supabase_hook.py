"""Supabase Custom Access Token hook (SEC-07): ``deploy/supabase/sql/001_...sql``.

The file runs in Supabase's own database, not in the Alembic chain, so it is tested on a
scratch database that imitates the parts of Supabase it touches (``auth.users``, the Data API
roles and ``supabase_auth_admin``).
"""

from __future__ import annotations

import json
import re
import secrets
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text

from bomagent_testing.fixtures import DbUrls

pytestmark = pytest.mark.integration

HOOK_SQL = (
    Path(__file__).resolve().parents[4] / "deploy/supabase/sql/001_custom_access_token_hook.sql"
)
FN = "public.bomagent_custom_access_token_hook"
ROLES = ("anon", "authenticated", "service_role", "supabase_auth_admin")


def _url(base: str, **parts: str) -> str:
    return make_url(base).set(**parts).render_as_string(hide_password=False)


def _run(url: str, sql: str) -> None:
    eng = create_engine(url, isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.exec_driver_sql(sql.replace("%", "%%"))
    eng.dispose()


@pytest.fixture
def supabase_like(db_urls: DbUrls):
    """Scratch database with ``auth.users``; created roles are dropped again (they are
    cluster-wide and their presence changes how later migrations behave)."""
    superuser = _url(db_urls.admin, database="postgres")
    eng = create_engine(superuser, isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        created = [
            r
            for r in ROLES
            if not conn.execute(
                text("SELECT count(*) FROM pg_roles WHERE rolname = :r"), {"r": r}
            ).scalar_one()
        ]
        for r in created:
            conn.execute(text(f"CREATE ROLE {r} NOLOGIN"))
        db = f"test_hook_{secrets.token_hex(4)}"
        conn.execute(text(f"CREATE DATABASE {db}"))
    eng.dispose()
    target = _url(db_urls.admin, database=db)
    _run(
        target,
        "CREATE SCHEMA auth; CREATE TABLE auth.users (id uuid PRIMARY KEY, email text,"
        " email_confirmed_at timestamptz); ALTER SCHEMA auth OWNER TO supabase_auth_admin;"
        " ALTER TABLE auth.users OWNER TO supabase_auth_admin;",  # GoTrue owns its schema
    )
    try:
        yield target
    finally:
        _run(superuser, f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        for r in created:
            _run(superuser, f"DROP ROLE IF EXISTS {r}")


def _hook(target: str, user_id: str, claims: dict[str, object] | None = None) -> dict:
    """Call the hook as GoTrue does: as ``supabase_auth_admin``."""
    event = {"user_id": user_id, "claims": claims or {"sub": user_id}, "authentication_method": "x"}
    eng = create_engine(target, isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.execute(text("SET ROLE supabase_auth_admin"))
        out = conn.execute(text(f"SELECT {FN}(CAST(:e AS jsonb))"), {"e": json.dumps(event)})
        result = out.scalar_one()
    eng.dispose()
    return result  # type: ignore[no-any-return]


def test_email_verified_comes_from_the_server_side_confirmation(supabase_like: str) -> None:
    _run(supabase_like, HOOK_SQL.read_text())
    ok, pending = str(uuid.uuid4()), str(uuid.uuid4())
    _run(
        supabase_like,
        f"INSERT INTO auth.users VALUES ('{ok}', 'a@x.eu', now()), ('{pending}', 'b@x.eu', NULL)",
    )
    forged = {"sub": pending, "user_metadata": {"email_verified": True}, "email_verified": True}
    out = _hook(supabase_like, ok)
    assert out["claims"]["email_verified"] is True
    assert out["user_id"] == ok  # the rest of the event is returned untouched
    # a user-writable claim never survives: the hook overwrites it with the server value
    denied = _hook(supabase_like, pending, forged)
    assert denied["claims"]["email_verified"] is False
    assert denied["claims"]["user_metadata"] == {"email_verified": True}  # untouched, ignored
    assert _hook(supabase_like, str(uuid.uuid4()))["claims"]["email_verified"] is False
    assert _hook(supabase_like, "not-a-uuid")["claims"]["email_verified"] is False


def test_only_gotrue_may_execute_the_hook(supabase_like: str) -> None:
    _run(supabase_like, HOOK_SQL.read_text())
    _run(supabase_like, HOOK_SQL.read_text())  # idempotent
    eng = create_engine(supabase_like)
    with eng.connect() as conn:
        for role, allowed in (
            ("supabase_auth_admin", True),
            ("anon", False),
            ("authenticated", False),
            ("service_role", False),
        ):
            got = conn.execute(
                text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                {"r": role, "f": f"{FN}(jsonb)"},
            ).scalar_one()
            assert got is allowed, role
        public = conn.execute(
            text(
                "SELECT count(*) FROM pg_proc p, aclexplode(p.proacl) a WHERE p.proname ="
                " 'bomagent_custom_access_token_hook' AND a.grantee = 0"
            )
        ).scalar_one()
        assert public == 0  # PUBLIC has no EXECUTE
        secdef = conn.execute(
            text(
                "SELECT prosecdef FROM pg_proc WHERE proname = 'bomagent_custom_access_token_hook'"
            )
        ).scalar_one()
        assert secdef is False  # runs as the caller, no privilege amplification
    eng.dispose()


def test_down_section_removes_the_function(supabase_like: str) -> None:
    sql = HOOK_SQL.read_text()
    _run(supabase_like, sql)
    down = re.search(r"^-- (DROP FUNCTION .*;)$", sql, re.M)
    assert down is not None
    _run(supabase_like, down.group(1))
    eng = create_engine(supabase_like)
    with eng.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM pg_proc WHERE proname LIKE 'bomagent_custom_access%'")
            ).scalar_one()
            == 0
        )
    eng.dispose()
