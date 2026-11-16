#!/usr/bin/env python3
"""List the DECISIONS_LOG rows that still wait for the owner's acceptance (audit DOC-02).

Rows are the Markdown table in ``docs/DECISIONS_LOG.md``: date, question, decision, rationale and
a last column that says ``yes`` while the owner has not accepted the assumption. Exit status 1 when
a pending row is older than ``--max-age-days`` (default 60): the nightly workflow runs this for
visibility, it never blocks a pull request.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

DEFAULT_LOG = Path(__file__).resolve().parents[1] / "docs" / "DECISIONS_LOG.md"


@dataclass(frozen=True)
class Row:
    date: date | None  # None = the first cell is not an ISO date
    question: str
    pending: bool


def parse(text: str) -> list[Row]:
    rows: list[Row] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        # cells are separated by " | "; the closing pipe is optional in the log
        body = line.removeprefix("|").removesuffix("|").strip()
        cells = [c.strip() for c in body.split(" | ")]
        first = cells[0]
        if len(cells) < 2 or first == "Date" or set(first) <= {"-", ":", "|", " "}:
            continue
        try:
            when: date | None = date.fromisoformat(first)
        except ValueError:
            when = None
        rows.append(Row(when, cells[1], cells[-1].lower() == "yes"))
    return rows


def stale(rows: list[Row], *, today: date, max_age_days: int) -> list[Row]:
    """Pending rows older than the limit (a pending row without a valid date counts as stale)."""
    return [
        r for r in rows if r.pending and (r.date is None or (today - r.date).days > max_age_days)
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", nargs="?", default=str(DEFAULT_LOG))
    ap.add_argument("--max-age-days", type=int, default=60)
    ap.add_argument("--today", type=date.fromisoformat, default=None, help="for tests")
    args = ap.parse_args(argv)
    rows = parse(Path(args.log).read_text(encoding="utf-8"))
    today = args.today or datetime.now(UTC).date()
    pending = [r for r in rows if r.pending]
    old = stale(rows, today=today, max_age_days=args.max_age_days)
    print(f"decisions: {len(rows)}, pending acceptance: {len(pending)}")
    for r in old:
        print(f"  waiting > {args.max_age_days} days: {r.date or '(no date)'}  {r.question[:100]}")
    return 1 if old else 0


if __name__ == "__main__":
    sys.exit(main())
