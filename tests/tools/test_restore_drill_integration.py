"""End to end: pg_dump of a migrated database -> tools/restore_drill.py -> verified (OPS-05).

The source database is built from the schema of the session's migrated test database plus
a known tenant and audit chain, so other tests' (deliberately broken) chains do not leak in.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import restore_drill as rd

pytestmark = [
    pytest.mark.integration,
    # CI runners have the client tools: there a missing tool fails instead of skipping
    pytest.mark.skipif(
        not os.environ.get("CI")
        and not all(shutil.which(t) for t in ("psql", "pg_dump", "pg_restore")),
        reason="needs the PostgreSQL client tools (psql, pg_dump, pg_restore)",
    ),
]


def _libpq(url: str, database: str) -> str:
    return (
        make_url(url)
        .set(drivername="postgresql", database=database)
        .render_as_string(hide_password=False)
    )


def _sh(*cmd: str, url: str) -> None:
    target, env = rd._conn(url)
    subprocess.run([*cmd, target], check=True, capture_output=True, text=True, env=env)


@pytest.fixture
def source(db_urls) -> Iterator[tuple[str, str]]:
    """(server admin URL, source database URL): a fresh database with the current schema."""
    server = _libpq(db_urls.admin, "postgres")
    name = f"drill_src_{secrets.token_hex(4)}"
    rd._psql(server, f'CREATE DATABASE "{name}"')
    src = _libpq(db_urls.admin, name)
    schema = subprocess.run(
        ["pg_dump", "--schema-only", "-Fc", rd._conn(_libpq(db_urls.admin, db_urls.database))[0]],
        check=True,
        capture_output=True,
        env=rd._conn(db_urls.admin)[1],
    ).stdout
    target, env = rd._conn(src)
    subprocess.run(
        ["pg_restore", "--no-owner", "--no-privileges", "--exit-on-error", "-d", target],
        input=schema,
        check=True,
        capture_output=True,
        env=env,
    )
    try:
        yield server, src
    finally:
        rd._psql(server, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _seed(src: str, events: int) -> str:
    tid = str(uuid.uuid4())
    inserts = [
        "INSERT INTO audit.events (id, tenant_id, actor_type, actor_id, action, object_type,"
        f" object_id) VALUES (gen_random_uuid(), '{tid}', 'user', 'u1', 'org.created', 'org',"
        f" '{tid}')"
    ] * events
    rd._psql(
        src,
        f"SET app.tenant_id = '{tid}'",
        f"INSERT INTO tenancy.tenants (id, slug, name) VALUES ('{tid}', 'd-{tid[:8]}', 'd')",
        *inserts,
    )
    return tid


def _drill(server: str, src: str, tmp_path: Path, *extra: str) -> int:
    dump = tmp_path / "src.dump"
    _sh("pg_dump", "-Fc", "-f", str(dump), url=src)
    scratch = f"restore_drill_{secrets.token_hex(4)}"
    argv = ["--dump", str(dump), "--scratch-db", scratch, "--confirm-scratch", scratch]
    return rd.main([*argv, "--cleanup", *extra], env={rd.ENV_ADMIN_URL: server})


def test_a_good_dump_is_verified_per_tenant(source, tmp_path, capsys):
    server, src = source
    tid = _seed(src, 3)
    assert _drill(server, src, tmp_path) == rd.EXIT_OK
    out = capsys.readouterr().out
    assert f"verify_chain {tid}: checked=3 ok" in out
    assert "RESULT: restore verified" in out


def test_a_tampered_chain_fails(source, tmp_path, capsys):
    server, src = source
    tid = _seed(src, 3)
    rd._psql(
        src,
        "ALTER TABLE audit.events DISABLE TRIGGER append_only",
        f"UPDATE audit.events SET action = 'x.forged' WHERE tenant_id = '{tid}' AND seq = 2",
    )
    assert _drill(server, src, tmp_path) == rd.EXIT_FAILED
    assert "BROKEN at seq 2" in capsys.readouterr().out


def test_an_empty_dump_fails_unless_allowed(source, tmp_path):
    server, src = source
    assert _drill(server, src, tmp_path) == rd.EXIT_FAILED
    assert _drill(server, src, tmp_path, "--allow-empty") == rd.EXIT_OK
