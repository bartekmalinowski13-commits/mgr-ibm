"""Alembic environment (online mode only; offline SQL scripts are not used)."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=None,
            version_table_schema="public",
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
