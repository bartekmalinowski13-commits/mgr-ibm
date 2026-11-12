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


def test_admin_url_verifies_the_server_certificate_when_a_ca_bundle_is_set() -> None:
    url = admin_url_from_env(
        {
            "BOMAGENT_ADMIN_USER": "bomagent_admin",
            "BOMAGENT_ADMIN_PASSWORD": "x",
            "BOMAGENT_DATABASE_HOST": "db.internal",
            "BOMAGENT_DB_SSL_ROOT_CERT": "/etc/ssl/rds/global-bundle.pem",
        }
    )
    query = make_url(url).query
    assert query["sslmode"] == "verify-full"
    assert query["sslrootcert"] == "/etc/ssl/rds/global-bundle.pem"


SUPABASE_ROLES = ("anon", "authenticated", "service_role")


def _scalar(url: str, sql: str, **params: object) -> object:
    eng = create_engine(url)
    with eng.connect() as conn:
        value = conn.execute(text(sql), params).scalar_one()
    eng.dispose()
    return value


def _vector_is_trusted(url: str) -> bool:
    return bool(
        _scalar(
            url,
            "SELECT bool_or(trusted) FROM pg_available_extension_versions WHERE name = 'vector'",
        )
    )


def _url(base: str, **parts: str) -> str:
    return make_url(base).set(**parts).render_as_string(hide_password=False)


@pytest.mark.parametrize("name", ["postgres", "template0", "template1"])
def test_refuses_to_take_over_a_system_database(db_urls: DbUrls, name: str) -> None:
    """Supabase's own ``postgres`` database stays Supabase's: the app needs its own."""
    with pytest.raises(ValueError, match="dedicated database"):
        prepare_database(_url(db_urls.admin, database=name))
    with pytest.raises(ValueError, match="dedicated database"):
        prepare_database(db_urls.admin, database=name)


def test_supabase_like_admin_creates_and_prepares_its_own_database(db_urls: DbUrls) -> None:
    """Supabase's ``postgres`` role: CREATEROLE + CREATEDB, not a superuser, connected to
    the ``postgres`` database. It creates ``bomagent`` and hands it to the migrator."""
    superuser = _url(db_urls.admin, database="postgres")
    tag = secrets.token_hex(4)
    admin, admin_pw, db = f"test_supa_{tag}", secrets.token_hex(12), f"test_own_{tag}"
    _exec(
        superuser,
        f"CREATE ROLE {admin} LOGIN CREATEDB CREATEROLE PASSWORD '{admin_pw}'",
        # what PostgreSQL 16 gives the creator of a role (on Supabase the admin creates ours)
        f"GRANT {MIGRATOR_ROLE}, {APP_ROLE}, {PLATFORM_ROLE} TO {admin}"
        " WITH ADMIN TRUE, INHERIT FALSE, SET FALSE",
    )
    admin_url = _url(superuser, username=admin, password=admin_pw)
    # the same passwords again: exercises ALTER ROLE ... PASSWORD as the non-superuser
    passwords = {
        MIGRATOR_ROLE: make_url(db_urls.migrator).password or "",
        APP_ROLE: make_url(db_urls.app).password or "",
        PLATFORM_ROLE: make_url(db_urls.platform).password or "",
    }
    target = _url(db_urls.admin, database=db)
    try:
        try:
            prepare_database(admin_url, passwords, database=db)
        except RuntimeError as exc:
            # Supabase lets its postgres role install pgvector (supautils); a plain local
            # non-superuser cannot install the untrusted extension (unless template1 has
            # it): the run created the database and stopped with a clear error, the
            # superuser installs the extension and the (idempotent) next run completes.
            if "pgvector" not in str(exc):
                raise
            _exec(target, "CREATE EXTENSION IF NOT EXISTS vector")
            prepare_database(admin_url, passwords, database=db)
        prepare_database(admin_url, database=db)  # idempotent
        owner = _scalar(
            target,
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()",
        )
        assert owner == MIGRATOR_ROLE
        assert _scalar(target, "SELECT count(*) FROM pg_extension WHERE extname = 'vector'") == 1
        assert _scalar(
            target, "SELECT has_database_privilege(:r, current_database(), 'CONNECT')", r=APP_ROLE
        )
        maintenance_owner = _scalar(
            superuser, "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'postgres'"
        )
        assert maintenance_owner != MIGRATOR_ROLE  # Supabase's database was not touched
        upgrade(_url(db_urls.migrator, database=db))
        assert _scalar(_url(db_urls.app, database=db), "SELECT current_user") == APP_ROLE
    finally:
        _exec(
            superuser,
            f"DROP DATABASE IF EXISTS {db} WITH (FORCE)",
            f"DROP ROLE IF EXISTS {admin}",
        )


def test_missing_pgvector_privilege_is_reported_clearly(db_urls: DbUrls) -> None:
    superuser = _url(db_urls.admin, database="postgres")
    if _vector_is_trusted(superuser):
        pytest.skip("pgvector is a trusted extension on this server")
    tag = secrets.token_hex(4)
    admin, admin_pw, db = f"test_novec_{tag}", secrets.token_hex(12), f"test_novec_{tag}"
    _exec(
        superuser,
        f"CREATE ROLE {admin} LOGIN CREATEDB CREATEROLE PASSWORD '{admin_pw}'",
        f"GRANT {MIGRATOR_ROLE}, {APP_ROLE}, {PLATFORM_ROLE} TO {admin}"
        " WITH ADMIN TRUE, INHERIT FALSE, SET FALSE",
        f"CREATE DATABASE {db} OWNER {admin} TEMPLATE template0"  # no pgvector inside
        " ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'",
    )
    try:
        with pytest.raises(RuntimeError, match="cannot install pgvector"):
            prepare_database(_url(superuser, username=admin, password=admin_pw), database=db)
    finally:
        _exec(
            superuser,
            f"DROP DATABASE IF EXISTS {db} WITH (FORCE)",
            f"DROP ROLE IF EXISTS {admin}",
        )


def test_supabase_data_api_roles_get_no_access(db_urls: DbUrls) -> None:
    """With Supabase's API roles present, ``upgrade`` revokes every privilege on our
    database and schemas from them (and CONNECT from PUBLIC)."""
    superuser = _url(db_urls.admin, database="postgres")
    created = [
        r
        for r in SUPABASE_ROLES
        if not _scalar(superuser, "SELECT count(*) FROM pg_roles WHERE rolname = :r", r=r)
    ]
    db = f"test_supa_api_{secrets.token_hex(4)}"
    _exec(superuser, *(f"CREATE ROLE {r} NOLOGIN" for r in created), f"CREATE DATABASE {db}")
    target = _url(db_urls.admin, database=db)
    try:
        prepare_database(target)
        _exec(target, "GRANT USAGE ON SCHEMA public TO anon")  # as a Supabase default would
        upgrade(_url(db_urls.migrator, database=db))
        for role in SUPABASE_ROLES:
            assert not _scalar(
                target, "SELECT has_database_privilege(:r, current_database(), 'CONNECT')", r=role
            )
            for schema in ("app", "tenancy", "audit", "kb", "projects", "runs", "bom", "public"):
                assert not _scalar(
                    target, "SELECT has_schema_privilege(:r, :s, 'USAGE')", r=role, s=schema
                ), (role, schema)
            assert not _scalar(
                target, "SELECT has_table_privilege(:r, 'tenancy.tenants', 'SELECT')", r=role
            )
        for role in (APP_ROLE, PLATFORM_ROLE):  # our runtime roles keep their access
            assert _scalar(
                target, "SELECT has_database_privilege(:r, current_database(), 'CONNECT')", r=role
            )
        assert _scalar(_url(db_urls.app, database=db), "SELECT current_user") == APP_ROLE
    finally:
        _exec(
            superuser,
            f"DROP DATABASE IF EXISTS {db} WITH (FORCE)",
            *(f"DROP ROLE IF EXISTS {r}" for r in created),
        )


def test_plain_postgres_keeps_default_database_privileges(db_urls: DbUrls) -> None:
    """Without Supabase's roles (AWS, local) nothing is revoked from PUBLIC."""
    supabase_roles = _scalar(
        db_urls.admin,
        "SELECT count(*) FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')",
    )
    assert supabase_roles == 0
    public_connect = _scalar(
        db_urls.admin,
        "SELECT datacl IS NULL OR EXISTS (SELECT 1 FROM aclexplode(datacl) a"
        " WHERE a.grantee = 0 AND a.privilege_type = 'CONNECT')"
        " FROM pg_database WHERE datname = current_database()",
    )
    assert public_connect is True


def test_bootstrap_cli_prepares_the_named_database(monkeypatch: pytest.MonkeyPatch) -> None:
    import bomagent_migrations as m

    calls: list[tuple[str, dict[str, str], str | None]] = []

    def fake(url: str, pw: dict[str, str], *, database: str | None = None) -> None:
        calls.append((url, pw, database))

    monkeypatch.setattr(m, "prepare_database", fake)
    monkeypatch.setattr("sys.argv", ["bomagent-migrate", "bootstrap"])
    monkeypatch.setenv("BOMAGENT_ADMIN_DATABASE_URL", "postgresql+psycopg://postgres:x@h/postgres")
    monkeypatch.setenv("BOMAGENT_DATABASE_NAME", "bomagent")
    monkeypatch.setenv("BOMAGENT_APP_PASSWORD", "a")
    for name in ("BOMAGENT_MIGRATOR_PASSWORD", "BOMAGENT_PLATFORM_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    m.main()
    assert calls == [("postgresql+psycopg://postgres:x@h/postgres", {APP_ROLE: "a"}, "bomagent")]
