"""tools/restore_drill.py only ever targets an explicitly named, new scratch database (OPS-05)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import restore_drill as rd

URL = "postgresql://admin:pw@db.example.invalid:5432/postgres"


@pytest.fixture
def dump(tmp_path: Path) -> Path:
    f = tmp_path / "x.dump"
    f.write_bytes(b"PGDMP")
    return f


@pytest.fixture(autouse=True)
def no_database(monkeypatch: pytest.MonkeyPatch):
    def boom(*a, **k):
        raise AssertionError("the test must not reach a database")

    monkeypatch.setattr(rd, "_psql", boom)
    monkeypatch.setattr(rd.subprocess, "run", boom)


def call(dump: Path, scratch: str, confirm: str | None = None, env=None, *extra: str) -> int:
    argv = [
        "--dump",
        str(dump),
        "--scratch-db",
        scratch,
        "--confirm-scratch",
        scratch if confirm is None else confirm,
        *extra,
    ]
    return rd.main(argv, env={} if env is None else env)


@pytest.mark.parametrize(
    "name",
    [
        "bomagent",
        "postgres",
        "template1",
        "prod_restore_drill_x",
        "restore_drill_",
        "restore_drill_UP",
        "restore_drill_a-b",
    ],
)
def test_refuses_names_that_are_not_scratch(dump, name, capsys):
    assert call(dump, name, env={rd.ENV_ADMIN_URL: URL}) == rd.EXIT_REFUSED
    assert "refused" in capsys.readouterr().err


def test_refuses_when_confirmation_differs(dump):
    env = {rd.ENV_ADMIN_URL: URL}
    assert call(dump, "restore_drill_a", "restore_drill_b", env) == rd.EXIT_REFUSED


def test_refuses_without_admin_url_or_dump(dump, tmp_path):
    assert call(dump, "restore_drill_a") == rd.EXIT_REFUSED
    missing = tmp_path / "nope.dump"
    assert call(missing, "restore_drill_a", env={rd.ENV_ADMIN_URL: URL}) == rd.EXIT_REFUSED


def test_refuses_non_postgres_url(dump):
    assert call(dump, "restore_drill_a", env={rd.ENV_ADMIN_URL: "http://x/y"}) == rd.EXIT_REFUSED


def test_missing_required_arguments_exit_with_usage_error():
    with pytest.raises(SystemExit) as e:
        rd.main(["--scratch-db", "restore_drill_a"], env={})
    assert e.value.code == 2


def test_dry_run_prints_plan_and_touches_nothing(dump, capsys):
    assert call(dump, "restore_drill_a", None, None, "--dry-run", "--cleanup") == rd.EXIT_OK
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "restore_drill_a" in out
    assert "drop database" in out


def test_dry_run_still_validates_the_name(dump):
    assert call(dump, "bomagent", None, None, "--dry-run") == rd.EXIT_REFUSED


def test_db_url_replaces_only_the_database():
    assert rd.db_url(URL + "?sslmode=require", "restore_drill_a") == (
        "postgresql://admin:pw@db.example.invalid:5432/restore_drill_a?sslmode=require"
    )


def test_refuses_existing_database_without_creating_or_dropping(dump, monkeypatch):
    monkeypatch.setattr(rd.shutil, "which", lambda _: "/bin/x")
    calls: list[str] = []

    def fake(url, sql):
        calls.append(sql)
        return "1"  # the pg_database lookup finds it

    monkeypatch.setattr(rd, "_psql", fake)
    assert call(dump, "restore_drill_a", env={rd.ENV_ADMIN_URL: URL}) == rd.EXIT_REFUSED
    assert all("CREATE" not in c and "DROP" not in c for c in calls)
