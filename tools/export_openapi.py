"""Write the API contract (OpenAPI 3.1) to services/api/openapi.json (ADR-0015)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from bomagent_api.app import Settings, create_app
from bomagent_api.auth import DevAuthenticator
from bomagent_api.routes import ApiServices


def openapi() -> dict[str, object]:
    services = ApiServices(  # placeholders: only the route table matters for the schema
        engine=None,  # type: ignore[arg-type]
        store=None,  # type: ignore[arg-type]
        ingest_queue=None,  # type: ignore[arg-type]
        runs_queue=None,  # type: ignore[arg-type]
        authenticator=DevAuthenticator("x" * 32),
        catalog=None,  # type: ignore[arg-type]
    )
    app = create_app(Settings(environment="test"), services)
    return app.openapi()


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "services/api/openapi.json")
    out.write_text(json.dumps(openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
