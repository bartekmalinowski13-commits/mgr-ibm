"""Run the local stack without Docker: Postgres (already running) + moto + fake LLM + API
+ workers as plain processes. For sessions/machines without a Docker daemon.

    uv run python tools/dev/native_stack.py            # Ctrl-C stops everything
    uv run python tools/dev/native_stack.py --token-only

Needs a PostgreSQL 16 with pgvector reachable with a superuser URL (--admin-url or
BOMAGENT_TEST_DATABASE_URL). Local-only passwords; never point this at a shared server.
Prints a dev token for an organisation; the web app uses it with
``VITE_API_MODE=http VITE_DEV_TOKEN=<token> pnpm --filter @bomagent/web dev``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

from bomagent_api.auth import DevAuthenticator
from bomagent_common.db import platform_transaction
from bomagent_migrations import bootstrap, upgrade

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".native-stack"
PASSWORDS = {
    "bomagent_migrator": "local-migrator",
    "bomagent_app": "local-app",
    "bomagent_platform": "local-platform",
}
SECRET = "local-dev-secret-change-me-0123456789"
MOTO = "http://127.0.0.1:5000"
ORG_SLUG = "pomorskie-lab-medtech"


def database(admin_url: str, name: str) -> dict[str, str]:
    base = make_url(admin_url).set(drivername="postgresql+psycopg")
    bootstrap(base.render_as_string(hide_password=False), PASSWORDS)
    eng = create_engine(base.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        if not conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
        ).first():
            conn.execute(text(f'CREATE DATABASE "{name}" OWNER bomagent_migrator'))
    eng.dispose()
    db = base.set(database=name)
    eng = create_engine(db.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    with eng.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text(f'GRANT CONNECT ON DATABASE "{name}" TO bomagent_app, bomagent_platform'))
    eng.dispose()
    urls = {
        role: db.set(username=role, password=pw).render_as_string(hide_password=False)
        for role, pw in PASSWORDS.items()
    }
    upgrade(urls["bomagent_migrator"])
    return urls


async def organisation(platform_url: str) -> uuid.UUID:
    engine = create_async_engine(platform_url)
    async with platform_transaction(engine) as conn:
        row = (
            await conn.execute(
                text("SELECT id FROM tenancy.tenants WHERE slug = :s"), {"s": ORG_SLUG}
            )
        ).first()
        if row is None:
            tid = uuid.uuid4()
            await conn.execute(
                text("INSERT INTO tenancy.tenants (id, slug, name) VALUES (:id, :slug, :name)"),
                {"id": tid, "slug": ORG_SLUG, "name": "Pomorskie Laboratorium Medtech"},
            )
        else:
            tid = uuid.UUID(str(row[0]))
    await engine.dispose()
    return tid


def aws_init() -> None:
    sys.path.insert(0, str(ROOT / "deploy" / "compose" / "aws-init"))
    os.environ["BOMAGENT_AWS_ENDPOINT_URL"] = MOTO
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")
    import init  # type: ignore[import-not-found]

    init.main()


def wait_http(url: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"{url} did not come up")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--admin-url",
        default=os.environ.get(
            "BOMAGENT_TEST_DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/postgres",
        ),
    )
    parser.add_argument("--db", default="bomagent_native")
    parser.add_argument("--token-only", action="store_true")
    args = parser.parse_args()

    urls = database(args.admin_url, args.db)
    tenant = asyncio.run(organisation(urls["bomagent_platform"]))
    token = DevAuthenticator(SECRET).issue(tenant, "bartek", ["owner"])
    STATE.mkdir(exist_ok=True)
    (STATE / "token").write_text(token)
    if args.token_only:
        print(token)
        return

    common = {
        **os.environ,
        "BOMAGENT_ENVIRONMENT": "local",
        "BOMAGENT_HOST": "127.0.0.1",
        "BOMAGENT_DATABASE_URL": urls["bomagent_app"],
        "BOMAGENT_AWS_ENDPOINT_URL": MOTO,
        "BOMAGENT_AWS_REGION": "eu-central-1",
        "BOMAGENT_FILES_BUCKET": "bomagent-local-files",
        "AWS_ACCESS_KEY_ID": "local",
        "AWS_SECRET_ACCESS_KEY": "local",
        "BOMAGENT_LLM_GATEWAY_URL": "http://127.0.0.1:4010",
        "BOMAGENT_LLM_GATEWAY_KEY": "local-only",
        "BOMAGENT_ALLOW_LOCAL_MODELS": "true",
    }
    queue = f"{MOTO}/123456789012"
    services = {
        "moto": ([sys.executable, "-m", "moto.server", "-H", "127.0.0.1", "-p", "5000"], {}),
        "fake-llm": (
            [sys.executable, "-m", "bomagent_llm.fake_server"],
            {
                "BOMAGENT_PORT": "4010",
                "BOMAGENT_FAKE_LLM_SIMULATOR": "bomagent_agents.simulators:simulate",
            },
        ),
        "api": (
            [sys.executable, "-m", "bomagent_api"],
            {
                "BOMAGENT_PORT": "8000",
                "BOMAGENT_PLATFORM_DATABASE_URL": urls["bomagent_platform"],
                "BOMAGENT_INGEST_QUEUE_URL": f"{queue}/ingest",
                "BOMAGENT_RUNS_QUEUE_URL": f"{queue}/runs",
                "BOMAGENT_KB_QUEUE_URL": f"{queue}/kb",
                "BOMAGENT_AUTH_MODE": "dev",
                "BOMAGENT_DEV_AUTH_SECRET": SECRET,
            },
        ),
        "ingest-worker": (
            [sys.executable, "-m", "bomagent_ingest"],
            {
                "BOMAGENT_PORT": "8101",
                "BOMAGENT_QUEUE_URL": f"{queue}/ingest",
                "BOMAGENT_QUEUE_WAIT_SECONDS": "1",
            },
        ),
        "agent-worker": (
            [sys.executable, "-m", "bomagent_agent_worker"],
            {
                "BOMAGENT_PORT": "8102",
                "BOMAGENT_QUEUE_URL": f"{queue}/runs",
                "BOMAGENT_QUEUE_WAIT_SECONDS": "1",
            },
        ),
        "kb-indexer": (
            [sys.executable, "-m", "bomagent_kb_indexer"],
            {
                "BOMAGENT_PORT": "8103",
                "BOMAGENT_QUEUE_URL": f"{queue}/kb",
                "BOMAGENT_QUEUE_WAIT_SECONDS": "1",
            },
        ),
    }
    logs = STATE / "logs"
    logs.mkdir(exist_ok=True)
    procs: list[subprocess.Popen[bytes]] = []

    def start(name: str) -> None:
        cmd, env = services[name]
        log = (logs / f"{name}.log").open("wb")
        procs.append(subprocess.Popen(cmd, env=common | env, stdout=log, stderr=subprocess.STDOUT))

    try:
        start("moto")
        wait_http(f"{MOTO}/moto-api/")
        aws_init()
        start("fake-llm")
        wait_http("http://127.0.0.1:4010/healthz")
        for name in ("api", "ingest-worker", "agent-worker", "kb-indexer"):
            start(name)
        wait_http("http://127.0.0.1:8000/healthz")
        print(f"native stack up · API http://127.0.0.1:8000 · logs {logs}")
        print(f"dev token (organisation {tenant}):\n{token}")
        signal.sigwait({signal.SIGINT, signal.SIGTERM})
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=10)


if __name__ == "__main__":
    main()
