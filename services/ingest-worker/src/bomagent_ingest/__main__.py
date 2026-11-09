"""Run with ``python -m bomagent_ingest`` (container entrypoint)."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "bomagent_ingest.app:create_app",
        factory=True,
        host=os.environ.get("BOMAGENT_HOST", "0.0.0.0"),  # noqa: S104 - container port
        port=int(os.environ.get("BOMAGENT_PORT", "8000")),
        log_config=None,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
