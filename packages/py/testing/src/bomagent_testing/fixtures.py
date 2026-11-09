"""pytest plugin with database fixtures (see README)."""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Generator, Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.ext.asyncio import AsyncEngine

from bomagent_common.db import make_engine, platform_transaction
from bomagent_common.tenancy import TenantContext
from bomagent_migrations import APP_ROLE, PLATFORM_ROLE, bootstrap, upgrade

PG_IMAGE = "pgvector/pgvector:pg16"


@dataclass(frozen=True)
class DbUrls:
    admin: str
    migrator: str
    app: str
    platform: str
    database: str


def _admin_url() -> Generator[str, None, None]:
    url = os.environ.get("BOMAGENT_TEST_DATABASE_URL")
    if url:
        yield url
        return
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError as exc:  # pragma: no cover
        pytest.fail(f"no BOMAGENT_TEST_DATABASE_URL and testcontainers unavailable: {exc}")
    try:
        container = PostgresContainer(PG_IMAGE, driver="psycopg")
        container.start()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.fail(
            "PostgreSQL for integration tests unavailable: set BOMAGENT_TEST_DATABASE_URL "
            f"or provide Docker for Testcontainers ({type(exc).__name__}: {exc})"
        )
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.fixture(scope="session")
def db_urls() -> Iterator[DbUrls]:
    gen = _admin_url()
    admin = next(gen)
    base = make_url(admin).set(drivername="postgresql+psycopg")
    dbname = f"bomagent_test_{secrets.token_hex(4)}"
    pwds = {r: secrets.token_hex(16) for r in ("bomagent_migrator", APP_ROLE, PLATFORM_ROLE)}
    bootstrap(base.render_as_string(hide_password=False), pwds)

    eng = create_engine(base.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}" OWNER bomagent_migrator'))
    eng.dispose()

    db_admin = base.set(database=dbname)
    eng = create_engine(
        db_admin.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    with eng.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{dbname}" TO {APP_ROLE}, {PLATFORM_ROLE}'))
    eng.dispose()

    def role_url(role: str) -> str:
        return db_admin.set(username=role, password=pwds[role]).render_as_string(
            hide_password=False
        )

    upgrade(role_url("bomagent_migrator"))
    urls = DbUrls(
        admin=db_admin.render_as_string(hide_password=False),
        migrator=role_url("bomagent_migrator"),
        app=role_url(APP_ROLE),
        platform=role_url(PLATFORM_ROLE),
        database=dbname,
    )
    try:
        yield urls
    finally:
        eng = create_engine(
            base.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
        )
        with eng.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
        eng.dispose()
        gen.close()


@pytest.fixture(scope="session")
async def app_engine(db_urls: DbUrls) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(db_urls.app)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def platform_engine(db_urls: DbUrls) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(db_urls.platform)
    yield engine
    await engine.dispose()


MakeTenant = Callable[..., Awaitable[TenantContext]]


async def create_tenant(
    platform_engine: AsyncEngine,
    slug: str | None = None,
    *,
    roles: frozenset[str] = frozenset({"owner"}),
    actor_id: str = "user-test",
) -> TenantContext:
    tid = uuid.uuid4()
    slug = slug or f"t-{tid.hex[:12]}"
    async with platform_transaction(platform_engine) as conn:
        await conn.execute(
            text("INSERT INTO tenancy.tenants (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": tid, "slug": slug, "name": slug},
        )
    return TenantContext(tenant_id=tid, actor_id=actor_id, roles=roles)


@pytest.fixture
def make_tenant(platform_engine: AsyncEngine) -> MakeTenant:
    async def _make(slug: str | None = None, **kw: object) -> TenantContext:
        return await create_tenant(platform_engine, slug, **kw)  # type: ignore[arg-type]

    return _make
