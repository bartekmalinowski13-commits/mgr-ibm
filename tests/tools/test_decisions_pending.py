"""tools/decisions_pending.py: which DECISIONS_LOG rows still wait for the owner (DOC-02)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import decisions_pending as dp

LOG = """# Decision log

Intro text with a | pipe that is not a row.

| Date | Question | Decision | Rationale | Needs acceptance |
|---|---|---|---|---|
| 2026-08-01 | Old question | Old decision | because | yes |
| 2026-08-02 | Old but no acceptance needed | x | y | no |
| 2026-11-10 | Recent question | decision with a `|` inside? no | why | yes |
| 2026-11-12 | Row with a longer rationale that mentions yes | d | contains yes and more | no |
| not-a-date | Malformed date | d | r | yes |
| 2026-07-01 | Old but accepted | d | r | accepted |
"""


def test_parses_rows_and_flags_only_pending_ones():
    rows = dp.parse(LOG)
    pending = [r for r in rows if r.pending]
    assert [r.date.isoformat() if r.date else None for r in pending] == [
        "2026-08-01",
        "2026-11-10",
        None,  # the malformed row is pending too
    ]
    assert {r.question for r in pending} == {"Old question", "Recent question", "Malformed date"}


def test_a_pending_row_with_a_malformed_date_is_surfaced_as_stale():
    rows = dp.parse(LOG)
    assert any(r.date is None and r.pending for r in rows)
    assert "Malformed date" in {
        r.question for r in dp.stale(rows, today=date(2026, 11, 16), max_age_days=9999)
    }


def test_stale_rows_are_pending_rows_older_than_the_limit():
    rows = dp.parse(LOG)
    stale = dp.stale(rows, today=date(2026, 11, 16), max_age_days=60)
    assert [r.question for r in stale] == ["Old question", "Malformed date"]
    clean = dp.parse(LOG.replace("| not-a-date | Malformed date | d | r | yes |\n", ""))
    assert dp.stale(clean, today=date(2026, 11, 16), max_age_days=200) == []


def test_main_exit_code_reflects_stale_rows(tmp_path, capsys):
    f = tmp_path / "log.md"
    f.write_text(LOG)
    assert dp.main([str(f), "--today", "2026-11-16", "--max-age-days", "60"]) == 1
    out = capsys.readouterr().out
    assert "Old question" in out
    assert "pending acceptance: 3" in out  # old, recent and malformed
    f.write_text(LOG.replace("| not-a-date | Malformed date | d | r | yes |\n", ""))
    assert dp.main([str(f), "--today", "2026-11-16", "--max-age-days", "400"]) == 0
    assert dp.main([str(f), "--today", "2026-11-16", "--max-age-days", "60"]) == 1


def test_the_real_log_parses_and_has_rows():
    log = Path(__file__).resolve().parents[2] / "docs" / "DECISIONS_LOG.md"
    rows = dp.parse(log.read_text())
    assert len(rows) > 50
    assert all(r.date is not None for r in rows)  # every real row has an ISO date
