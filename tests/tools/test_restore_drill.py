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


# --- verification (fake psql/pg_restore): the drill must never "verify" what it cannot see ---

TID = "11111111-1111-1111-1111-111111111111"


class FakeDb:
    """Answers the drill's queries; records every psql session."""

    def __init__(self, tenants: list[str], events: int, chain: dict[str, str]) -> None:
        self.tenants, self.events, self.chain = tenants, events, chain
        self.sessions: list[tuple[str, ...]] = []

    def psql(self, url: str, *statements: str) -> str:
        self.sessions.append(statements)
        sql = statements[-1]
        if "pg_database" in sql or sql.startswith(("CREATE", "DROP")):
            return ""
        if sql == "SELECT count(*) FROM tenancy.tenants":
            return str(len(self.tenants))
        if sql == "SELECT count(*) FROM audit.events":
            return str(self.events)
        if sql.startswith("SELECT id FROM tenancy.tenants"):
            return "\n".join(self.tenants)
        if "verify_chain" in sql:
            tid = statements[0].split("'")[1]
            return self.chain[tid]
        raise AssertionError(f"unexpected SQL {sql}")


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch):
    def install(tenants: list[str], events: int, chain: dict[str, str]) -> FakeDb:
        db = FakeDb(tenants, events, chain)
        monkeypatch.setattr(rd.shutil, "which", lambda _: "/bin/x")
        monkeypatch.setattr(rd, "_psql", db.psql)
        monkeypatch.setattr(rd.subprocess, "run", lambda *a, **k: None)  # pg_restore
        return db

    return install


def drill(dump: Path, *extra: str) -> int:
    return call(dump, "restore_drill_a", None, {rd.ENV_ADMIN_URL: URL}, *extra)


def test_verify_chain_runs_in_the_tenant_context(dump, fake_db, capsys):
    db = fake_db([TID], 3, {TID: "3|3|"})
    assert drill(dump) == rd.EXIT_OK
    session = next(s for s in db.sessions if "verify_chain" in s[-1])
    assert session[0] == f"SET app.tenant_id = '{TID}'"  # same psql session as the check
    assert "restore verified" in capsys.readouterr().out


def test_empty_dump_fails_unless_explicitly_allowed(dump, fake_db, capsys):
    fake_db([], 0, {})
    assert drill(dump) == rd.EXIT_FAILED
    captured = capsys.readouterr()
    assert "no tenants" in captured.err
    assert "FAILED" in captured.out
    fake_db([], 0, {})
    assert drill(dump, "--allow-empty") == rd.EXIT_OK


def test_tenant_without_audit_events_fails(dump, fake_db, capsys):
    fake_db([TID], 0, {TID: "0|0|"})
    assert drill(dump) == rd.EXIT_FAILED
    assert "no audit events" in capsys.readouterr().err


def test_chain_check_that_walked_fewer_events_than_visible_fails(dump, fake_db, capsys):
    fake_db([TID], 3, {TID: "3|0|"})
    assert drill(dump) == rd.EXIT_FAILED
    assert "checked 0 of 3" in capsys.readouterr().err


def test_events_outside_the_listed_tenants_fail(dump, fake_db, capsys):
    fake_db([TID], 5, {TID: "3|3|"})
    assert drill(dump) == rd.EXIT_FAILED
    assert "cover 3 of 5" in capsys.readouterr().err


def test_broken_chain_fails(dump, fake_db, capsys):
    fake_db([TID], 3, {TID: "3|2|2"})
    assert drill(dump) == rd.EXIT_FAILED
    assert "BROKEN at seq 2" in capsys.readouterr().out


def test_a_psql_error_fails(dump, fake_db, monkeypatch):
    db = fake_db([TID], 3, {TID: "3|3|"})

    def failing(url: str, *statements: str) -> str:
        if "verify_chain" in statements[-1]:
            raise rd.subprocess.CalledProcessError(3, "psql", stderr="insufficient_privilege")
        return db.psql(url, *statements)

    monkeypatch.setattr(rd, "_psql", failing)
    assert drill(dump) == rd.EXIT_FAILED


def test_tenant_ids_are_never_interpolated_unchecked(dump, fake_db, capsys):
    db = fake_db(["x'; DROP DATABASE prod; --"], 1, {})
    assert drill(dump) == rd.EXIT_FAILED
    assert not any("DROP DATABASE prod" in sql for s in db.sessions for sql in s)
    assert "not a UUID" in capsys.readouterr().err


def test_password_goes_to_the_environment_not_argv():
    url, env = rd._conn("postgresql://admin:s3cret@db.example.invalid:5432/restore_drill_a")
    assert "s3cret" not in url
    assert url == "postgresql://admin@db.example.invalid:5432/restore_drill_a"
    assert env["PGPASSWORD"] == "s3cret"
