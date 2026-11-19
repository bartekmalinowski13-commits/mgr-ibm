"""Run with ``python -m bomagent_agent_worker`` (container entrypoint).

SIGTERM is handled by ``bomagent_common.shutdown``: long-lived responses end and queue
consumers stop claiming at once, then the lifespan teardown runs within the kill timeout.
"""

from __future__ import annotations

from typing import Any

from bomagent_common import shutdown


def build_app() -> Any:
    from bomagent_agent_worker.app import create_app

    return create_app()


def main() -> None:
    shutdown.serve(build_app)


if __name__ == "__main__":
    main()
