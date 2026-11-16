"""``bomagent-ops``: read-only, local operator helpers (OPS-03).

No cloud access and no database connection: the commands print information a human then
uses through the normal, audited paths. Mutating tools (requeue, purge) are deliberately
absent until they can run inside the tenant context (RLS) with an audit event.

bomagent-ops env                  BOMAGENT_* settings of this shell, secrets hidden
bomagent-ops queries [NAME]       read-only SQL for stuck outbox / dead queue messages
"""

from __future__ import annotations

import os
from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False, help="BOM Agent operator helpers")

_SECRET_MARKERS = ("KEY", "SECRET", "PASSWORD", "TOKEN", "URL")

_TENANT_NOTE = (
    "-- RLS applies: run inside one tenant, e.g.\n"
    "--   BEGIN; SELECT set_config('app.tenant_id', '<tenant uuid>', true); <query>; COMMIT;\n"
)

#: name -> (description, SQL). Every statement is a plain SELECT.
QUERIES: dict[str, tuple[str, str]] = {
    "outbox-pending": (
        "outbox rows not yet sent and not dead, oldest first",
        "SELECT id, queue, attempts, last_error, created_at FROM app.outbox\n"
        " WHERE sent_at IS NULL AND dead_at IS NULL ORDER BY created_at LIMIT 100;",
    ),
    "outbox-dead": (
        "outbox rows that exhausted their delivery attempts",
        "SELECT id, queue, attempts, last_error, created_at, dead_at FROM app.outbox\n"
        " WHERE dead_at IS NOT NULL ORDER BY dead_at DESC LIMIT 100;",
    ),
    "queue-dead": (
        "Postgres-queue messages that were dead-lettered",
        "SELECT id, queue, receive_count, enqueued_at, dead_at FROM app.queue_messages\n"
        " WHERE dead_at IS NOT NULL ORDER BY dead_at DESC LIMIT 100;",
    ),
}


def redact(name: str, value: str) -> str:
    return "<set, hidden>" if any(m in name.upper() for m in _SECRET_MARKERS) else value


@app.command()
def env() -> None:
    """Print BOMAGENT_* variables of this shell (secret-like values are hidden)."""
    for name in sorted(os.environ):
        if name.startswith("BOMAGENT_"):
            typer.echo(f"{name}={redact(name, os.environ[name])}")


@app.command()
def queries(name: Annotated[str | None, typer.Argument()] = None) -> None:
    """List the read-only SQL helpers, or print one."""
    if name is None:
        for key, (description, _) in QUERIES.items():
            typer.echo(f"{key:<16} {description}")
        return
    if name not in QUERIES:
        typer.echo(f"unknown query {name!r}; choose from: {', '.join(QUERIES)}", err=True)
        raise typer.Exit(2)
    typer.echo(_TENANT_NOTE + QUERIES[name][1])


if __name__ == "__main__":
    app()
