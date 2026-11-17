"""tools/migration_lint.py: static safety lint of the Alembic revisions (OPS-08)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import migration_lint as ml


def _write(tmp: Path, rev: str, parent: str | None, upgrade_sql: str, downgrade_sql: str) -> None:
    parent_literal = "None" if parent is None else f'"{parent}"'
    (tmp / f"{rev}_x.py").write_text(
        f'''
from alembic import op

revision = "{rev}"
down_revision = {parent_literal}

UPGRADE = ["""{upgrade_sql}"""]
DOWNGRADE = ["""{downgrade_sql}"""]


def upgrade() -> None:
    for s in UPGRADE:
        op.execute(s)


def downgrade() -> None:
    for s in DOWNGRADE:
        op.execute(s)
'''
    )


def _rules(tmp: Path) -> set[str]:
    return {f.rule for f in ml.lint(tmp)}


def test_the_real_revisions_are_clean() -> None:
    assert [str(f) for f in ml.lint()] == []


def test_every_baseline_waiver_has_a_reason() -> None:
    assert all(reason.strip() for reason in ml.BASELINE.values())


def test_a_clean_chain_passes(tmp_path: Path) -> None:
    _write(tmp_path, "0001", None, "CREATE TABLE a.t (id int)", "DROP TABLE a.t")
    _write(
        tmp_path,
        "0002",
        "0001",
        "CREATE TABLE a.u (id int); CREATE INDEX i ON a.u (id)",
        "DROP TABLE a.u",
    )
    assert ml.lint(tmp_path) == []


@pytest.mark.parametrize(
    ("sql", "rule"),
    [
        ("ALTER TABLE a.t ALTER COLUMN id SET NOT NULL", "set-not-null"),
        ("ALTER TABLE a.t ALTER COLUMN id TYPE bigint", "alter-column-type"),
        ("ALTER TABLE a.t ADD COLUMN n int NOT NULL", "add-not-null-column"),
        ("LOCK TABLE a.t", "lock-table"),
        ("TRUNCATE a.t", "truncate"),
        ("ALTER TABLE a.t DROP COLUMN id", "drop-column"),
        ("ALTER TABLE a.t RENAME COLUMN id TO k", "rename"),
        ("CREATE INDEX i2 ON a.t (id)", "index-on-existing-table"),
    ],
)
def test_lock_hazards_are_flagged(tmp_path: Path, sql: str, rule: str) -> None:
    _write(tmp_path, "0001", None, "CREATE TABLE a.s (id int)", "DROP TABLE a.s")
    _write(tmp_path, "0002", "0001", sql, "SELECT 1")
    assert rule in _rules(tmp_path)


def test_add_not_null_column_with_default_is_fine(tmp_path: Path) -> None:
    _write(tmp_path, "0001", None, "CREATE TABLE a.t (id int)", "DROP TABLE a.t")
    _write(tmp_path, "0002", "0001", "ALTER TABLE a.t ADD COLUMN n int NOT NULL DEFAULT 0", "x")
    assert "add-not-null-column" not in _rules(tmp_path)


def test_a_missing_or_noop_downgrade_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "0001", None, "CREATE TABLE a.t (id int)", "DROP TABLE a.t")
    (tmp_path / "0002_x.py").write_text(
        'revision = "0002"\ndown_revision = "0001"\n\n\ndef upgrade() -> None:\n    pass\n\n\n'
        "def downgrade() -> None:\n    pass\n"
    )
    assert "no-downgrade" in _rules(tmp_path)


def test_a_branch_or_second_head_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "0001", None, "CREATE TABLE a.t (id int)", "DROP TABLE a.t")
    _write(tmp_path, "0002", "0001", "CREATE TABLE a.u (id int)", "DROP TABLE a.u")
    (tmp_path / "0003_y.py").write_text(
        (tmp_path / "0002_x.py").read_text().replace('"0002"', '"0003"')
    )
    assert "chain" in _rules(tmp_path)


def test_file_name_must_start_with_the_revision(tmp_path: Path) -> None:
    _write(tmp_path, "0001", None, "CREATE TABLE a.t (id int)", "DROP TABLE a.t")
    (tmp_path / "0001_x.py").rename(tmp_path / "0009_x.py")
    assert "naming" in _rules(tmp_path)


def test_main_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert ml.main() == 0
    assert "0 finding(s)" in capsys.readouterr().out


def test_drop_table_of_an_existing_table_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "0001", None, "CREATE TABLE a.t (id int)", "DROP TABLE a.t")
    _write(tmp_path, "0002", "0001", "DROP TABLE a.t", "CREATE TABLE a.t (id int)")
    assert "drop-table" in _rules(tmp_path)


def test_a_contract_revision_must_stand_alone(tmp_path: Path) -> None:
    _write(tmp_path, "0001", None, "CREATE TABLE a.t (id int, old int)", "DROP TABLE a.t")
    _write(
        tmp_path,
        "0002",
        "0001",
        'ALTER TABLE a.t ADD COLUMN new int""", """ALTER TABLE a.t DROP COLUMN old',
        "SELECT 1",
    )
    assert "contract-mixed" in _rules(tmp_path)


def test_a_lone_drop_column_is_not_mixed(tmp_path: Path) -> None:
    _write(tmp_path, "0001", None, "CREATE TABLE a.t (id int, old int)", "DROP TABLE a.t")
    _write(tmp_path, "0002", "0001", "ALTER TABLE a.t DROP COLUMN old", "SELECT 1")
    assert "contract-mixed" not in _rules(tmp_path)
