#!/usr/bin/env python3
"""Restore drill: restore a dump into a NEW scratch database and verify it (OPS-05).

Safety model (the script can never touch production data):
  * The only database it writes to is the one named by ``--scratch-db``. The name must start
    with ``restore_drill_`` and must not exist yet: the script CREATEs it and refuses to
    continue when it is already there. It never drops, truncates or alters an existing database.
  * ``--confirm-scratch`` must repeat the name exactly (a typo cannot point it elsewhere).
  * The dump is only read. Connection strings come from the environment, never from argv
    (``BOMAGENT_DRILL_ADMIN_URL`` = a server where the scratch database may be created).
  * ``--cleanup`` drops only the scratch database this run created.
  * ``--dry-run`` prints the plan and needs no database or credentials.

Steps: create scratch DB -> pg_restore -> row counts of key tables -> ``audit.verify_chain``
for every tenant. Exit code 0 = restore verified, 1 = verification failed, 2 = refused/usage.
Runbook: docs/platform/runbooks/backup-restore-dr.md
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SCRATCH_PREFIX = "restore_drill_"
SCRATCH_RE = re.compile(r"^restore_drill_[a-z0-9_]{1,40}$")
ENV_ADMIN_URL = "BOMAGENT_DRILL_ADMIN_URL"
COUNT_TABLES = ("tenancy.tenants", "audit.events")

EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2


class RefusedError(Exception):
    """The arguments or environment do not describe a safe drill."""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="restore_drill.py",
        description="Restore a pg_dump (custom format) into a new scratch database and verify it.",
    )
    p.add_argument("--dump", required=True, type=Path, help="pg_dump -Fc file (read only)")
    p.add_argument("--scratch-db", required=True, help=f"new database name, {SCRATCH_PREFIX}*")
    p.add_argument("--confirm-scratch", required=True, help="repeat --scratch-db to confirm")
    p.add_argument("--cleanup", action="store_true", help="drop the scratch database afterwards")
    p.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    return p


def validate(args: argparse.Namespace, env: dict[str, str]) -> str:
    """Return the admin URL (or '' for a dry run); raise RefusedError on anything unsafe."""
    if not SCRATCH_RE.match(args.scratch_db):
        raise RefusedError(
            f"--scratch-db must match {SCRATCH_RE.pattern} (a name starting with {SCRATCH_PREFIX})"
        )
    if args.confirm_scratch != args.scratch_db:
        raise RefusedError("--confirm-scratch does not match --scratch-db")
    if args.dry_run:
        return ""
    if not args.dump.is_file():
        raise RefusedError(f"dump file not found: {args.dump}")
    url = env.get(ENV_ADMIN_URL, "")
    if not url:
        raise RefusedError(
            f"set {ENV_ADMIN_URL} (server where the scratch database may be created)"
        )
    if not urlsplit(url).scheme.startswith("postgres"):
        raise RefusedError(f"{ENV_ADMIN_URL} must be a postgresql:// URL")
    return url


def db_url(admin_url: str, dbname: str) -> str:
    p = urlsplit(admin_url)
    return urlunsplit((p.scheme, p.netloc, "/" + dbname, p.query, ""))


def _psql(url: str, sql: str) -> str:
    out = subprocess.run(
        ["psql", url, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip()


def plan(args: argparse.Namespace) -> list[str]:
    steps = [
        f"create database {args.scratch_db} (must not exist)",
        f"pg_restore --no-owner --no-privileges {args.dump} into {args.scratch_db}",
        f"row counts: {', '.join(COUNT_TABLES)}",
        "audit.verify_chain for every tenancy.tenants row",
    ]
    if args.cleanup:
        steps.append(f"drop database {args.scratch_db} (created by this run)")
    return steps


def run(args: argparse.Namespace, admin_url: str) -> int:
    for tool in ("psql", "pg_restore"):
        if shutil.which(tool) is None:
            raise RefusedError(f"{tool} not found on PATH")
    name = args.scratch_db
    if _psql(admin_url, f"SELECT 1 FROM pg_database WHERE datname = '{name}'"):
        raise RefusedError(f"database {name} already exists; pick a new scratch name")
    _psql(admin_url, f'CREATE DATABASE "{name}"')
    target = db_url(admin_url, name)
    ok = True
    try:
        subprocess.run(
            [
                "pg_restore",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "-d",
                target,
                str(args.dump),
            ],
            check=True,
        )
        for table in COUNT_TABLES:
            print(f"rows {table}: {_psql(target, f'SELECT count(*) FROM {table}')}")
        tenants = _psql(target, "SELECT id FROM tenancy.tenants ORDER BY id").splitlines()
        for tid in tenants:
            row = _psql(
                target,
                "SELECT checked || '|' || coalesce(first_broken_seq::text, '') "
                f"FROM audit.verify_chain('{tid}')",
            )
            checked, _, broken = row.partition("|")
            status = "ok" if not broken else f"BROKEN at seq {broken}"
            print(f"verify_chain {tid}: checked={checked} {status}")
            ok = ok and not broken
    except subprocess.CalledProcessError as exc:
        print(f"restore drill failed: {exc}", file=sys.stderr)
        ok = False
    finally:
        if args.cleanup:
            _psql(admin_url, f'DROP DATABASE IF EXISTS "{name}"')
            print(f"dropped scratch database {name}")
    print("RESULT:", "restore verified" if ok else "restore FAILED verification")
    return EXIT_OK if ok else EXIT_FAILED


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env = dict(os.environ) if env is None else env
    try:
        admin_url = validate(args, env)
        if args.dry_run:
            print("DRY RUN - nothing will be touched. Plan:")
            for i, step in enumerate(plan(args), 1):
                print(f"  {i}. {step}")
            return EXIT_OK
        return run(args, admin_url)
    except RefusedError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
