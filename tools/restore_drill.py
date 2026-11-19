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
for every tenant, each in that tenant's own context (``app.tenant_id``; the function refuses to
run without it). Exit code 0 = restore verified, 1 = verification failed, 2 = refused/usage.

The drill fails loudly whenever it cannot verify: a dump without tenants (or one whose tenants
the admin role cannot see because of RLS) fails unless ``--allow-empty`` is given; tenants
without any audit event fail; and every tenant's ``checked`` must equal the number of its
events (a role that RLS hides rows from would otherwise "verify" an empty chain).
Runbook: docs/platform/runbooks/backup-restore-dr.md
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import uuid
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
    p.add_argument(
        "--allow-empty",
        action="store_true",
        help="accept a dump without tenants (otherwise an empty restore fails verification)",
    )
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


def _conn(url: str) -> tuple[str, dict[str, str]]:
    """The URL without its password, and the environment that carries the password: argv is
    visible to every user of the host (``ps``), the environment of the child is not."""
    p = urlsplit(url)
    env = dict(os.environ)
    if p.password is not None:
        env["PGPASSWORD"] = p.password
        host = p.hostname or ""
        if ":" in host:  # IPv6 literal
            host = f"[{host}]"
        user = f"{p.username}@" if p.username else ""
        port = f":{p.port}" if p.port else ""
        url = urlunsplit((p.scheme, f"{user}{host}{port}", p.path, p.query, ""))
    return url, env


def _psql(url: str, *statements: str) -> str:
    """Run ``statements`` in ONE psql session (so ``SET`` applies to the queries after it)."""
    target, env = _conn(url)
    cmd = ["psql", target, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
    for sql in statements:
        cmd += ["-c", sql]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    return out.stdout.strip()


class VerificationError(Exception):
    """The restored database could not be verified."""


def verify_tenant(target: str, tenant: str) -> tuple[int, str]:
    """``(checked, broken_seq or '')`` of one tenant's chain, verified in its own context.

    Raises VerificationError when the visible event count differs from what the chain
    check walked (the context did not apply) or the tenant has no audit event at all."""
    try:
        tid = str(uuid.UUID(tenant))  # never interpolate anything but a canonical UUID
    except ValueError as exc:
        raise VerificationError(f"tenant id {tenant!r} is not a UUID") from exc
    row = _psql(
        target,
        f"SET app.tenant_id = '{tid}'",
        f"SELECT (SELECT count(*) FROM audit.events WHERE tenant_id = '{tid}')"
        " || '|' || v.checked || '|' || coalesce(v.first_broken_seq::text, '')"
        f" FROM audit.verify_chain('{tid}') v",
    )
    visible, _, rest = row.partition("|")
    checked, _, broken = rest.partition("|")
    if int(visible) == 0:
        raise VerificationError(f"tenant {tid} has no audit events in the restore")
    if not broken and int(checked) != int(visible):
        raise VerificationError(f"tenant {tid}: verify_chain checked {checked} of {visible} events")
    return int(checked), broken


def plan(args: argparse.Namespace) -> list[str]:
    steps = [
        f"create database {args.scratch_db} (must not exist)",
        f"pg_restore --no-owner --no-privileges {args.dump} into {args.scratch_db}",
        f"row counts: {', '.join(COUNT_TABLES)}",
        "audit.verify_chain for every tenancy.tenants row, in that tenant's context",
        "fail on 0 tenants (unless --allow-empty) or a tenant without audit events",
    ]
    if args.cleanup:
        steps.append(f"drop database {args.scratch_db} (created by this run)")
    return steps


def verify_restore(target: str, *, allow_empty: bool) -> bool:
    """Row counts and every tenant's chain; False on a broken chain, VerificationError when
    the restore cannot be verified at all."""
    ok = True
    counts = {t: int(_psql(target, f"SELECT count(*) FROM {t}")) for t in COUNT_TABLES}
    for table, n in counts.items():
        print(f"rows {table}: {n}")
    tenants = _psql(target, "SELECT id FROM tenancy.tenants ORDER BY id").splitlines()
    if not tenants:
        if not allow_empty:
            raise VerificationError(
                "no tenants visible in the restore: an empty dump, or a role that RLS"
                " hides tenancy.tenants from (use a superuser/BYPASSRLS admin);"
                " pass --allow-empty only for a dump known to be empty"
            )
        print("no tenants (accepted: --allow-empty)")
    checked_total = 0
    for tid in tenants:
        checked, broken = verify_tenant(target, tid)
        checked_total += checked
        status = "ok" if not broken else f"BROKEN at seq {broken}"
        print(f"verify_chain {tid}: checked={checked} {status}")
        ok = ok and not broken
    if ok and checked_total != counts["audit.events"]:
        raise VerificationError(
            f"chains cover {checked_total} of {counts['audit.events']} audit events"
            " (events of tenants that are not in tenancy.tenants?)"
        )
    return ok


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
    restore_url, restore_env = _conn(target)
    try:
        subprocess.run(
            [
                "pg_restore",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "-d",
                restore_url,
                str(args.dump),
            ],
            check=True,
            env=restore_env,
        )
        ok = verify_restore(target, allow_empty=args.allow_empty)
    except VerificationError as exc:
        print(f"restore drill cannot verify: {exc}", file=sys.stderr)
        ok = False
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
        print(f"restore drill failed: {exc} {detail}".rstrip(), file=sys.stderr)
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
