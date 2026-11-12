"""Database schema of the platform (single source for all services).

Migrations are hand-written (no autogenerate) because every tenant table needs explicit
RLS policies that are reviewed like code (SECURITY.md, "Procesy"). Run them with a
dedicated migrator role, never with the application role.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping
from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, make_url, text
from sqlalchemy.exc import DBAPIError

__version__ = "0.1.0"

APP_ROLE = "bomagent_app"
PLATFORM_ROLE = "bomagent_platform"
MIGRATOR_ROLE = "bomagent_migrator"
ROLES = (MIGRATOR_ROLE, APP_ROLE, PLATFORM_ROLE)
#: databases the platform never takes over (Supabase's own ``postgres``, templates)
SYSTEM_DATABASES = frozenset({"postgres", "template0", "template1"})
#: Supabase's Data API (PostgREST) roles; when present they lose every privilege on our
#: database and schemas (see ``revoke_data_api_roles``). Absent in AWS and locally.
DATA_API_ROLES = ("anon", "authenticated", "service_role")
PASSWORD_ENV = {
    MIGRATOR_ROLE: "BOMAGENT_MIGRATOR_PASSWORD",
    APP_ROLE: "BOMAGENT_APP_PASSWORD",
    PLATFORM_ROLE: "BOMAGENT_PLATFORM_PASSWORD",
}


def _config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def bootstrap_sql() -> str:
    """SQL creating cluster-level roles (run once by an administrator)."""
    return resources.files(__package__).joinpath("bootstrap.sql").read_text(encoding="utf-8")


def bootstrap(admin_url: str, passwords: dict[str, str] | None = None) -> None:
    """Create roles (idempotent) and optionally set their passwords."""
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(bootstrap_sql()))
        for role, pwd in (passwords or {}).items():
            # role names come from our constant list, never from user input
            if role not in ROLES:
                raise ValueError(f"unknown role {role}")
            # ALTER ROLE takes no bind parameters: let PostgreSQL quote the literal itself
            stmt = conn.execute(
                text(
                    "SELECT format('ALTER ROLE %I WITH PASSWORD %L',"
                    " CAST(:r AS text), CAST(:p AS text))"
                ),
                {"r": role, "p": pwd},
            ).scalar_one()
            conn.exec_driver_sql(stmt.replace("%", "%%"))
    engine.dispose()


def prepare_database(
    admin_url: str, passwords: dict[str, str] | None = None, *, database: str | None = None
) -> None:
    """Prepare the platform database for migrations (idempotent).

    Run with the cluster administrator - in AWS the Aurora master user, on Supabase the
    ``postgres`` role; neither is a superuser (CREATEROLE + CREATEDB). Creates the roles,
    sets their passwords, creates ``database`` when it is given and differs from the one
    ``admin_url`` points at (Supabase: connect to ``postgres``, prepare ``bomagent``),
    installs pgvector (needs the administrator), hands the database (and with it the
    ``public`` schema, owned by ``pg_database_owner``) to the migrator and lets the
    runtime roles connect. System databases (``postgres``, templates) are never taken over.
    """
    url = make_url(admin_url)
    target = database or url.database or ""
    if target in SYSTEM_DATABASES:
        raise ValueError(
            f"refusing to take ownership of the {target!r} database: the platform needs a "
            "dedicated database (BOMAGENT_DATABASE_NAME, e.g. 'bomagent')"
        )
    bootstrap(admin_url, passwords)
    if target != url.database:
        engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": target}
            ).first()
            if exists is None:  # needs CREATEDB; the administrator owns it until the hand-over
                stmt = conn.execute(
                    text("SELECT format('CREATE DATABASE %I', CAST(:d AS text))"), {"d": target}
                ).scalar_one()
                conn.exec_driver_sql(stmt.replace("%", "%%"))
        engine.dispose()
        admin_url = url.set(database=target).render_as_string(hide_password=False)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        # before the hand-over: a trusted extension needs CREATE on the database
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except DBAPIError as exc:
            engine.dispose()
            raise RuntimeError(
                f"cannot install pgvector in {target!r} as {url.username!r}: install it as a "
                "role allowed to (Supabase: enable the 'vector' extension; Aurora: "
                "rds_superuser) and run the preparation again"
            ) from exc
        # a non-superuser may only give a database to a role it can SET ROLE to
        conn.execute(text(f"GRANT {MIGRATOR_ROLE} TO CURRENT_USER"))
        conn.execute(
            text(
                "DO $$ BEGIN EXECUTE format('ALTER DATABASE %I OWNER TO "
                f"{MIGRATOR_ROLE}', current_database()); END $$"
            )
        )
        conn.execute(
            text(
                "DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO "
                f"{APP_ROLE}, {PLATFORM_ROLE}', current_database()); END $$"
            )
        )
    engine.dispose()


def _ssl_query(env: Mapping[str, str]) -> dict[str, str]:
    if cert := env.get("BOMAGENT_DB_SSL_ROOT_CERT"):
        return {"sslmode": "verify-full", "sslrootcert": cert}
    return {"sslmode": env.get("BOMAGENT_DATABASE_SSLMODE", "require")}


def admin_url_from_env(env: Mapping[str, str]) -> str:
    """Administrator URL: ``BOMAGENT_ADMIN_DATABASE_URL`` or composed from parts.

    Composing in Python keeps passwords with URL-special characters (the Aurora master
    secret has punctuation) out of shell strings.
    """
    if url := env.get("BOMAGENT_ADMIN_DATABASE_URL"):
        return url
    return URL.create(
        "postgresql+psycopg",
        username=env["BOMAGENT_ADMIN_USER"],
        password=env["BOMAGENT_ADMIN_PASSWORD"],
        host=env["BOMAGENT_DATABASE_HOST"],
        port=int(env.get("BOMAGENT_DATABASE_PORT", "5432")),
        database=env.get("BOMAGENT_DATABASE_NAME", "bomagent"),
        query=_ssl_query(env),
    ).render_as_string(hide_password=False)


def passwords_from_env(env: Mapping[str, str]) -> dict[str, str]:
    """Role passwords present in the environment (missing ones are left unchanged)."""
    return {role: env[name] for role, name in PASSWORD_ENV.items() if env.get(name)}


#: Conditional: a no-op unless Supabase's API roles exist (plain PostgreSQL, AWS). Run as
#: the migrator, which owns the database and every schema of the platform.
REVOKE_DATA_API_ROLES_SQL = """
DO $$
DECLARE
    api_role text;
    schema_name text;
    found boolean := false;
BEGIN
    FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        CONTINUE WHEN NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role);
        found := true;
        EXECUTE format('REVOKE ALL ON DATABASE %I FROM %I', current_database(), api_role);
        FOR schema_name IN
            SELECT nspname FROM pg_namespace
            WHERE nspowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
               OR nspname = 'public'
        LOOP
            EXECUTE format('REVOKE ALL ON SCHEMA %I FROM %I', schema_name, api_role);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM %I',
                           schema_name, api_role);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM %I',
                           schema_name, api_role);
            EXECUTE format('REVOKE ALL ON ALL ROUTINES IN SCHEMA %I FROM %I',
                           schema_name, api_role);
        END LOOP;
    END LOOP;
    IF found THEN
        -- the API roles would otherwise still CONNECT through PUBLIC; our runtime roles
        -- have explicit CONNECT grants (prepare_database), the migrator owns the database
        EXECUTE format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC',
                       current_database());
        -- likewise the default USAGE of PUBLIC on schema public (pgvector's type lives
        -- there): only our runtime roles keep it
        REVOKE ALL ON SCHEMA public FROM PUBLIC;
        GRANT USAGE ON SCHEMA public TO bomagent_app, bomagent_platform;
    END IF;
END
$$
"""


def revoke_data_api_roles(url: str) -> None:
    """Supabase exposes the ``postgres`` database through its Data API with the roles
    ``anon``/``authenticated``/``service_role``. Our data lives in its own database, but
    as defence in depth those roles get no privilege on it or on any of our schemas."""
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.exec_driver_sql(REVOKE_DATA_API_ROLES_SQL.replace("%", "%%"))
    engine.dispose()


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(_config(url), revision)
    revoke_data_api_roles(url)


def downgrade(url: str, revision: str) -> None:
    command.downgrade(_config(url), revision)


def main() -> None:  # pragma: no cover - thin CLI wrapper
    parser = argparse.ArgumentParser(prog="bomagent-migrate")
    parser.add_argument("action", choices=["upgrade", "downgrade", "bootstrap"])
    parser.add_argument("--revision", default="head")
    args = parser.parse_args()
    if args.action == "bootstrap":
        prepare_database(
            admin_url_from_env(os.environ),
            passwords_from_env(os.environ),
            database=os.environ.get("BOMAGENT_DATABASE_NAME") or None,
        )
        return
    url = os.environ["BOMAGENT_MIGRATOR_DATABASE_URL"]
    if args.action == "upgrade":
        upgrade(url, args.revision)
    else:
        downgrade(url, args.revision)
