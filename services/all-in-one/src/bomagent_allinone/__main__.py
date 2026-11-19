"""Container entrypoint.

    python -m bomagent_allinone            # serve: API + workers + SPA (default)
    python -m bomagent_allinone migrate    # Alembic upgrade as the migrator role
    python -m bomagent_allinone bootstrap  # roles + own database, as the administrator

``migrate``/``bootstrap`` are ``bomagent-migrate upgrade|bootstrap`` (same environment
variables: ``BOMAGENT_MIGRATOR_DATABASE_URL``; ``BOMAGENT_ADMIN_DATABASE_URL``,
``BOMAGENT_DATABASE_NAME``, ``BOMAGENT_{MIGRATOR,APP,PLATFORM}_PASSWORD``).
"""

from __future__ import annotations

import sys
from typing import Any

from bomagent_common import shutdown

COMMANDS = {"serve", "migrate", "bootstrap"}


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else "serve"
    if command not in COMMANDS:
        raise SystemExit(f"usage: python -m bomagent_allinone [{'|'.join(sorted(COMMANDS))}]")
    if command in {"migrate", "bootstrap"}:
        import bomagent_migrations

        sys.argv = ["bomagent-migrate", "upgrade" if command == "migrate" else "bootstrap"]
        bomagent_migrations.main()
        return
    # SIGTERM ends open live-progress streams and stops the consumers claiming at once, so
    # the lifespan teardown (consumer grace, message release) runs within the host's kill
    # timeout; BOMAGENT_HOST/PORT, BOMAGENT_SHUTDOWN_GRACE_S (bomagent_common.shutdown)
    shutdown.serve(build_app)


def build_app() -> Any:
    from bomagent_allinone.app import create_app

    return create_app()


if __name__ == "__main__":
    main()
