"""Database schema of the platform (single source for all services).

Migrations are hand-written (no autogenerate) because every tenant table needs explicit
RLS policies that are reviewed like code (SECURITY.md, "Procesy"). Run them with a
dedicated migrator role, never with the application role.
"""

from __future__ import annotations

import argparse
import os
from importlib import resources
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

__version__ = "0.1.0"

APP_ROLE = "bomagent_app"
PLATFORM_ROLE = "bomagent_platform"


def _config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def bootstrap_sql() -> str:
    """SQL creating cluster-level roles (run once by an administrator)."""
    return resources.files(__package__).joinpath("bootstrap.sql").read_text(encoding="utf-8")


def bootstrap(admin_url: str, passwords: dict[str, str] | None = None) -> None:
    """Create roles (idempotent) and optionally set their passwords."""
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(bootstrap_sql()))
        for role, pwd in (passwords or {}).items():
            # role names come from our constant list, never from user input
            if role not in {APP_ROLE, PLATFORM_ROLE, "bomagent_migrator"}:
                raise ValueError(f"unknown role {role}")
            # ALTER ROLE takes no bind parameters: let PostgreSQL quote the literal itself
            stmt = conn.execute(
                text(
                    "SELECT format('ALTER ROLE %I WITH PASSWORD %L',"
                    " CAST(:r AS text), CAST(:p AS text))"
                ),
                {"r": role, "p": pwd},
            ).scalar_one()
            conn.exec_driver_sql(stmt.replace("%", "%%"))
    engine.dispose()


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(_config(url), revision)


def downgrade(url: str, revision: str) -> None:
    command.downgrade(_config(url), revision)


def main() -> None:  # pragma: no cover - thin CLI wrapper
    parser = argparse.ArgumentParser(prog="bomagent-migrate")
    parser.add_argument("action", choices=["upgrade", "downgrade", "bootstrap"])
    parser.add_argument("--revision", default="head")
    args = parser.parse_args()
    url = os.environ["BOMAGENT_MIGRATOR_DATABASE_URL"]
    if args.action == "bootstrap":
        bootstrap(url)
    elif args.action == "upgrade":
        upgrade(url, args.revision)
    else:
        downgrade(url, args.revision)
