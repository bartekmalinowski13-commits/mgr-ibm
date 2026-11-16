from __future__ import annotations

from typer.testing import CliRunner

from bomagent_cli.ops import QUERIES, app, redact

runner = CliRunner()


def test_redact_hides_secret_like_values():
    assert redact("BOMAGENT_SUPABASE_ANON_KEY", "abc") == "<set, hidden>"
    assert redact("BOMAGENT_DATABASE_URL", "postgresql://u:p@h/db") == "<set, hidden>"
    assert redact("BOMAGENT_ENVIRONMENT", "dev") == "dev"


def test_env_lists_only_bomagent_variables_without_secrets(monkeypatch):
    monkeypatch.setenv("BOMAGENT_ENVIRONMENT", "dev")
    monkeypatch.setenv("BOMAGENT_PLATFORM_PASSWORD", "hunter2")
    monkeypatch.setenv("UNRELATED", "x")
    result = runner.invoke(app, ["env"])
    assert result.exit_code == 0
    assert "BOMAGENT_ENVIRONMENT=dev" in result.output
    assert "BOMAGENT_PLATFORM_PASSWORD=<set, hidden>" in result.output
    assert "hunter2" not in result.output
    assert "UNRELATED" not in result.output


def test_queries_lists_names():
    result = runner.invoke(app, ["queries"])
    assert result.exit_code == 0
    for name in QUERIES:
        assert name in result.output


def test_queries_prints_read_only_sql_for_a_named_query():
    for name in QUERIES:
        result = runner.invoke(app, ["queries", name])
        assert result.exit_code == 0
        statements = [ln for ln in result.output.splitlines() if not ln.startswith("--")]
        sql = "\n".join(statements).lower()
        assert sql.lstrip().startswith("select")
        for verb in ("update ", "delete ", "insert ", "drop ", "truncate "):
            assert verb not in sql


def test_queries_unknown_name_fails():
    result = runner.invoke(app, ["queries", "nope"])
    assert result.exit_code == 2
