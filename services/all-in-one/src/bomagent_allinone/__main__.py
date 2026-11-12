"""Container entrypoint.

    python -m bomagent_allinone            # serve: API + workers + SPA (default)
    python -m bomagent_allinone migrate    # Alembic upgrade as the migrator role
    python -m bomagent_allinone bootstrap  # roles + own database, as the administrator

``migrate``/``bootstrap`` are ``bomagent-migrate upgrade|bootstrap`` (same environment
variables: ``BOMAGENT_MIGRATOR_DATABASE_URL``; ``BOMAGENT_ADMIN_DATABASE_URL``,
``BOMAGENT_DATABASE_NAME``, ``BOMAGENT_{MIGRATOR,APP,PLATFORM}_PASSWORD``).
"""

from __future__ import annotations

import os
import sys

import uvicorn

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
    uvicorn.run(
        "bomagent_allinone.app:create_app",
        factory=True,
        host=os.environ.get("BOMAGENT_HOST", "0.0.0.0"),  # noqa: S104 - container port
        port=int(os.environ.get("BOMAGENT_PORT", "8000")),
        log_config=None,
        proxy_headers=True,  # trusted proxies: uvicorn's FORWARDED_ALLOW_IPS
    )


if __name__ == "__main__":
    main()
