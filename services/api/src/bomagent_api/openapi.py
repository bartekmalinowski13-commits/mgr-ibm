"""Print the OpenAPI 3.1 contract (``just openapi`` writes services/api/openapi.json)."""

from __future__ import annotations

import json
import sys

from bomagent_api.app import openapi_document


def main() -> None:
    sys.stdout.write(json.dumps(openapi_document(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
