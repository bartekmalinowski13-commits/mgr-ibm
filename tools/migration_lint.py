"""Static lint of the Alembic revisions in packages/py/db-migrations (OPS-08).

No database needed: revisions are parsed with ``ast``. Checks:

* one linear chain, one head, file name starts with the ``revision``;
* every revision has a non-trivial ``downgrade`` (and a non-empty ``DOWNGRADE`` list when
  it uses the list convention);
* lock-time hazards in the upgrade SQL: ``SET NOT NULL``, ``ALTER COLUMN ... TYPE``,
  ``ADD COLUMN ... NOT NULL`` without ``DEFAULT``, ``LOCK TABLE``, ``TRUNCATE``,
  ``DROP COLUMN``/``RENAME`` and ``CREATE INDEX`` on a table the same revision did not create;
* expand/contract (OPS-04): ``DROP TABLE`` of a table the revision did not create, and any
  ``DROP COLUMN``/``DROP TABLE`` revision that also does other changes (a contract step
  must stand alone, see packages/py/db-migrations/README.md "Expand/contract policy").

Existing revisions are frozen: findings that predate this lint are recorded in ``BASELINE``
with the reason. New revisions get no free pass - add a baseline entry only with a reason
and a review. ``python tools/migration_lint.py`` exits 1 on any finding.
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

VERSIONS = (
    Path(__file__).resolve().parents[1]
    / "packages/py/db-migrations/src/bomagent_migrations/versions"
)

#: (revision, rule) -> why it is acceptable.
BASELINE: dict[tuple[str, str], str] = {
    ("0011", "index-on-existing-table"): (
        "already applied; replaces app.outbox indexes (pilot-scale table, small build lock)"
    ),
    ("0014", "index-on-existing-table"): (
        "already applied; partial unique index on projects.projects (pilot-scale table)"
    ),
}

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("set-not-null", re.compile(r"\bSET\s+NOT\s+NULL\b", re.I)),
    ("alter-column-type", re.compile(r"\bALTER\s+COLUMN\s+\S+\s+(SET\s+DATA\s+)?TYPE\b", re.I)),
    ("lock-table", re.compile(r"^\s*LOCK\s+TABLE\b", re.I)),
    ("truncate", re.compile(r"^\s*TRUNCATE\b", re.I)),
    ("drop-column", re.compile(r"\bDROP\s+COLUMN\b", re.I)),
    ("rename", re.compile(r"\bRENAME\s+(COLUMN|TO)\b", re.I)),
]
_DROP_COLUMN = re.compile(r"\bDROP\s+COLUMN\b", re.I)
_DROP_TABLE = re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([\w.\"]+)", re.I)
_ADD_COLUMN = re.compile(r"\bADD\s+COLUMN\b[^,;]*", re.I)
_CREATE_TABLE = re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.\"]+)", re.I)
_CREATE_INDEX = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?\S+\s+ON\s+"
    r"(?:ONLY\s+)?([\w.\"]+)",
    re.I,
)


@dataclass(frozen=True)
class Finding:
    revision: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.revision}: [{self.rule}] {self.detail}"


@dataclass
class Revision:
    path: Path
    revision: str
    down_revision: str | None
    upgrade_sql: list[str]
    has_real_downgrade: bool
    downgrade_list_empty: bool


def _assigned(tree: ast.Module, name: str) -> ast.expr | None:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return node.value
    return None


def _strings(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    return [
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def _is_trivial(fn: ast.FunctionDef) -> bool:
    body = [
        s
        for s in fn.body
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))  # docstring
    ]
    return not body or all(isinstance(s, ast.Pass | ast.Raise) for s in body)


def load(path: Path) -> Revision:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def literal(name: str) -> str | None:
        node = _assigned(tree, name)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    sql = _strings(_assigned(tree, "UPGRADE"))
    if "upgrade" in funcs:  # direct op.execute("...") calls
        sql += _strings(funcs["upgrade"])
    for node in tree.body:  # UPGRADE += [...] / UPGRADE.extend(...) built after the literal
        if isinstance(node, ast.AugAssign) and getattr(node.target, "id", "") == "UPGRADE":
            sql += _strings(node.value)
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and getattr(node.value.func.value, "id", "") == "UPGRADE"
        ):
            sql += _strings(node.value)
    down = _assigned(tree, "DOWNGRADE")
    return Revision(
        path=path,
        revision=literal("revision") or "",
        down_revision=literal("down_revision"),
        upgrade_sql=sql,
        has_real_downgrade="downgrade" in funcs and not _is_trivial(funcs["downgrade"]),
        downgrade_list_empty=isinstance(down, ast.List) and not down.elts,
    )


def lint_revisions(revisions: list[Revision]) -> list[Finding]:
    out: list[Finding] = []
    ids = [r.revision for r in revisions]
    parents = [r.down_revision for r in revisions]
    if len(set(ids)) != len(ids):
        out.append(Finding("*", "chain", "duplicate revision ids"))
    roots = [r for r in revisions if r.down_revision is None]
    if len(roots) != 1:
        out.append(Finding("*", "chain", f"expected one root revision, found {len(roots)}"))
    if len(set(parents)) != len(parents):
        out.append(Finding("*", "chain", "branch: two revisions share a parent"))
    heads = [r.revision for r in revisions if r.revision not in set(parents)]
    if len(heads) != 1:
        out.append(Finding("*", "chain", f"expected one head, found {heads}"))
    known = set(ids)
    for r in revisions:
        if not r.path.name.startswith(f"{r.revision}_"):
            out.append(Finding(r.revision, "naming", f"{r.path.name} does not start with id"))
        if r.down_revision is not None and r.down_revision not in known:
            out.append(Finding(r.revision, "chain", f"unknown parent {r.down_revision}"))
        if not r.has_real_downgrade:
            out.append(Finding(r.revision, "no-downgrade", "downgrade() missing or a no-op"))
        if r.downgrade_list_empty:
            out.append(Finding(r.revision, "no-downgrade", "DOWNGRADE list is empty"))
        created = {
            m.group(1).strip('"').lower() for s in r.upgrade_sql for m in _CREATE_TABLE.finditer(s)
        }
        stmts = [s for s in r.upgrade_sql if s.strip()]
        drops = [s for s in stmts if _DROP_COLUMN.search(s) or _DROP_TABLE.search(s)]
        if drops and len(stmts) > len(drops):
            out.append(
                Finding(
                    r.revision,
                    "contract-mixed",
                    "DROP COLUMN/TABLE in a revision that also does other changes",
                )
            )
        for stmt in r.upgrade_sql:
            flat = " ".join(stmt.split())
            for rule, pat in _RULES:
                if pat.search(stmt):
                    out.append(Finding(r.revision, rule, flat[:100]))
            for m in _DROP_TABLE.finditer(stmt):
                if m.group(1).strip('"').lower() not in created:
                    out.append(Finding(r.revision, "drop-table", m.group(1)))
            for m in _ADD_COLUMN.finditer(stmt):
                col = m.group(0)
                if re.search(r"\bNOT\s+NULL\b", col, re.I) and not re.search(
                    r"\bDEFAULT\b", col, re.I
                ):
                    out.append(Finding(r.revision, "add-not-null-column", " ".join(col.split())))
            for m in _CREATE_INDEX.finditer(stmt):
                if m.group(1).strip('"').lower() not in created:
                    out.append(Finding(r.revision, "index-on-existing-table", m.group(1)))
    return [f for f in out if (f.revision, f.rule) not in BASELINE]


def lint(versions: Path = VERSIONS) -> list[Finding]:
    files = sorted(p for p in versions.glob("*.py") if not p.name.startswith("__"))
    return lint_revisions([load(p) for p in files])


def main() -> int:
    findings = lint()
    for f in findings:
        print(f, file=sys.stderr)
    print(f"migration lint: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
